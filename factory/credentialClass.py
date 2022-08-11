#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2009 Fermi Research Alliance, LLC
# SPDX-License-Identifier: Apache-2.0

#
# Project:
#   glideinWMS
#
# File Version:
#
# Description:
#   Contains information about credentials
#

import base64
import gzip
import io
import os
import pwd
import re
import shutil
import sys

from abc import ABC, abstractmethod
from importlib import import_module
from io import StringIO

from glideinwms.lib import condorMonitor, logSupport

from . import glideFactoryInterface, glideFactoryLib

sys.path.append("/etc/gwms-frontend/plugin.d")
plugins = {}
SUPPORTED_AUTH_METHODS = [
    "grid_proxy",
    "cert_pair",
    "key_pair",
    "auth_file",
    "username_password",
    "idtoken",
    "scitoken",
]


class CredentialError(Exception):
    """defining new exception so that we can catch only the credential errors here
    and let the "real" errors propagate up
    """


class Credential(ABC):
    def __init__(self):
        pass

    @classmethod
    @abstractmethod
    def get_cred_type(self):
        pass

    # Next Methods - Get?


# Dictionary of Credentials
class Credentials(dict):
    def __setitem__(self, __k, __v):
        if not isinstance(__v, Credential):
            raise TypeError("Value must be a credential")
        super().__setitem__(__k, __v)


class scitoken(Credential):
    def __init__(self, cred_loc, sec_class, trust_dom, vm_id, vm_type, pilot_proxy, creation_script, update_freq):
        self.cred_type = "scitoken"
        self.cred_loc = cred_loc
        self.sec_class = sec_class
        self.trust_dom = trust_dom
        # Cloud fields
        self.vm_id = vm_id
        self.vm_type = vm_type
        self.pilot_proxy = pilot_proxy
        # Fields for renewal
        self.creation_script = creation_script
        self.update_frequency = update_freq

    @classmethod
    def get_cred_type(self):
        return "scitoken"


class grid_proxy(Credential):
    def __init__(self, cred_loc, sec_class, trust_dom, vm_id, vm_type, pilot_proxy, creation_script, update_freq):
        self.cred_type = "grid_proxy"
        self.cred_loc = cred_loc
        self.sec_class = sec_class
        self.trust_dom = trust_dom
        # Cloud fields
        self.vm_id = vm_id
        self.vm_type = vm_type
        self.pilot_proxy = pilot_proxy
        # Fields for renewal
        self.creation_script = creation_script
        self.update_frequency = update_freq

    @classmethod
    def get_cred_type(self):
        return "grid_proxy"


class cert_pair(Credential):
    def __init__(self, cert, certkey, sec_class, trust_dom, vm_id, vm_type, pilot_proxy, creation_script, update_freq):
        self.cred_type = "cert_pair"
        self.cert = cert
        self.certkey = certkey
        self.sec_class = sec_class
        self.trust_dom = trust_dom
        # Cloud fields
        self.vm_id = vm_id
        self.vm_type = vm_type
        self.pilot_proxy = pilot_proxy
        # Fields for renewal
        self.creation_script = creation_script
        self.update_frequency = update_freq

    @classmethod
    def get_cred_type(self):
        return "cert_pair"


class key_pair(Credential):
    def __init__(
        self,
        pub_key,
        priv_key,
        sec_class,
        trust_dom,
        vm_id,
        vm_type,
        pilot_proxy,
        creation_script,
        update_freq,
        rem_user,
    ):
        self.cred_type = "key_pair"
        self.pub_key = pub_key
        self.priv_key = priv_key
        self.sec_class = sec_class
        self.trust_dom = trust_dom
        # Cloud fields
        self.vm_id = vm_id
        self.vm_type = vm_type
        self.pilot_proxy = pilot_proxy
        # Fields for renewal
        self.creation_script = creation_script
        self.update_frequency = update_freq
        # Optional for Key_pair (Remote Username)
        self.rem_user = rem_user

    @classmethod
    def get_cred_type(self):
        return "key_pair"


class username_password(Credential):
    def __init__(
        self, username, password, sec_class, trust_dom, vm_id, vm_type, pilot_proxy, creation_script, update_freq
    ):
        self.cred_type = "username_password"
        self.username = username
        self.password = password
        self.sec_class = sec_class
        self.trust_dom = trust_dom
        # Cloud fields
        self.vm_id = vm_id
        self.vm_type = vm_type
        self.pilot_proxy = pilot_proxy
        # Fields for renewal
        self.creation_script = creation_script
        self.update_frequency = update_freq

    @classmethod
    def get_cred_type(self):
        return "username_password"


class auth_file(Credential):
    def __init__(self, file, sec_class, trust_dom, vm_id, vm_type, pilot_proxy, creation_script, update_freq, rem_user):
        self.cred_type = "auth_file"
        self.file = file
        self.sec_class = sec_class
        self.trust_dom = trust_dom
        # Cloud fields
        self.vm_id = vm_id
        self.vm_type = vm_type
        self.pilot_proxy = pilot_proxy
        # Fields for renewal
        self.creation_script = creation_script
        self.update_frequency = update_freq

    @classmethod
    def get_cred_type(self):
        return "auth_file"


class SubmitCredentials:
    def __init__(self, username, security_class):
        self.username = username
        self.security_class = security_class
        self.id = None  # id used for tacking the submit credentials
        self.cred_dir = ""  # location of credentials
        self.security_credentials = Credentials()
        self.identity_credentials = Credentials()

    def add_security_credential(self, cred_type, filename, prefix=""):
        """
        Adds a security credential.
        """
        if not glideFactoryLib.is_str_safe(filename):
            return False

        cred_fname = os.path.join(self.cred_dir, f"{prefix}{filename}")
        if not os.path.isfile(cred_fname):
            return False

        self.security_credentials[cred_type] = cred_fname
        return True

    def add_factory_credential(self, cred_type, absfname):
        """
        Adds a factory provided security credential.
        """
        if not os.path.isfile(absfname):
            return False

        self.security_credentials[cred_type] = absfname
        return True

    def add_identity_credential(self, cred_type, cred_str):
        """
        Adds an identity credential.
        """
        self.identity_credentials[cred_type] = cred_str
        return True


# Creates a credential
def create_cred(cred_type, **krx):
    class_dict = {}
    for i in Credential.__subclasses__():
        class_dict[i.get_cred_type()] = i

    try:
        cred = class_dict[cred_type](**krx)
    except KeyError:
        raise CredentialError(f"Unknown Credential type: {cred_type}")
    except TypeError:
        raise CredentialError(f"Incorrect parameters for credential {cred_type}: {krx}")
    return cred


def get_scitoken(elementDescript, trust_domain):
    """Look for a local SciToken specified for the trust domain.

    Args:
        elementDescript (ElementMergedDescript): element descript
        trust_domain (string): trust domain for the element

    Returns:
        string, None: SciToken or None if not found
    """

    scitoken_fullpath = ""
    cred_type_data = elementDescript.element_data.get("ProxyTypes")
    trust_domain_data = elementDescript.element_data.get("ProxyTrustDomains")
    if not cred_type_data:
        cred_type_data = elementDescript.frontend_data.get("ProxyTypes")
    if not trust_domain_data:
        trust_domain_data = elementDescript.frontend_data.get("ProxyTrustDomains")
    if trust_domain_data and cred_type_data:
        cred_type_map = eval(cred_type_data)
        trust_domain_map = eval(trust_domain_data)
        for cfname in cred_type_map:
            if cred_type_map[cfname] == "scitoken":
                if trust_domain_map[cfname] == trust_domain:
                    scitoken_fullpath = cfname

    if os.path.exists(scitoken_fullpath):
        try:
            logSupport.log.debug(f"found scitoken {scitoken_fullpath}")
            stkn = ""
            with open(scitoken_fullpath) as fbuf:
                for line in fbuf:
                    stkn += line
            stkn = stkn.strip()
            return stkn
        except Exception as err:
            logSupport.log.exception(f"failed to read scitoken: {err}")

    return None


def generate_credential(elementDescript, glidein_el, group_name, trust_domain):
    """Generates a credential with a credential generator plugin provided for the trust domain.

    Args:
        elementDescript (ElementMergedDescript): element descript
        glidein_el (dict): glidein element
        group_name (string): group name
        trust_domain (string): trust domain for the element

    Returns:
        string, None: Credential or None if not generated
    """

    ### The credential generator plugin should define the following function:
    # def get_credential(log:logger, group:str, entry:dict{name:str, gatekeeper:str}, trust_domain:str):
    # Generates a credential given the parameter

    # Args:
    # log:logger
    # group:str,
    # entry:dict{
    #     name:str,
    #     gatekeeper:str},
    # trust_domain:str,
    # Return
    # tuple
    #     token:str
    #     lifetime:int seconds of remaining lifetime
    # Exception
    # KeyError - miss some information to generate
    # ValueError - could not generate the token

    generator = None
    generators = elementDescript.element_data.get("CredentialGenerators")
    trust_domain_data = elementDescript.element_data.get("ProxyTrustDomains")
    if not generators:
        generators = elementDescript.frontend_data.get("CredentialGenerators")
    if not trust_domain_data:
        trust_domain_data = elementDescript.frontend_data.get("ProxyTrustDomains")
    if trust_domain_data and generators:
        generators_map = eval(generators)
        trust_domain_map = eval(trust_domain_data)
        for cfname in generators_map:
            if trust_domain_map[cfname] == trust_domain:
                generator = generators_map[cfname]
                logSupport.log.debug(f"found credential generator plugin {generator}")
                try:
                    if not generator in plugins:
                        plugins[generator] = import_module(generator)
                    entry = {
                        "name": glidein_el["attrs"].get("EntryName"),
                        "gatekeeper": glidein_el["attrs"].get("GLIDEIN_Gatekeeper"),
                        "factory": glidein_el["attrs"].get("AuthenticatedIdentity"),
                    }
                    stkn, _ = plugins[generator].get_credential(logSupport, group_name, entry, trust_domain)
                    return stkn
                except ModuleNotFoundError:
                    logSupport.log.warning(f"Failed to load credential generator plugin {generator}")
                except Exception as e:  # catch any exception from the plugin to prevent the frontend from crashing
                    logSupport.log.warning(f"Failed to generate credential: {e}.")

    return None


def get_globals_classads(factory_collector=glideFactoryInterface.DEFAULT_VAL):
    if factory_collector == glideFactoryInterface.DEFAULT_VAL:
        factory_collector = glideFactoryInterface.factoryConfig.factory_collector

    status_constraint = '(GlideinMyType=?="glideclientglobal")'

    status = condorMonitor.CondorStatus("any", pool_name=factory_collector)
    status.require_integrity(True)  # important, this dictates what gets submitted

    status.load(status_constraint)

    data = status.fetchStored()
    return data


# Helper for update_credential_file
def compress_credential(credential_data):
    with StringIO() as cfile:
        with gzip.GzipFile(fileobj=cfile, mode="wb") as f:
            # Calling a GzipFile object's close() method does not close fileobj, so cfile is available outside
            f.write(credential_data)
    return base64.b64encode(cfile.getvalue())


# Helper for update_credential_file
def safe_update(fname, credential_data):
    if not os.path.isfile(fname):
        # new file, create
        with os.open(fname, os.O_CREAT | os.O_WRONLY, 0o600) as file:
            file.write(credential_data)

    else:
        # old file exists, check if same content
        with open(fname) as fl:
            old_data = fl.read()

        #  if proxy_data == old_data nothing changed, done else
        if not (credential_data == old_data):
            # proxy changed, neeed to update
            # remove any previous backup file, if it exists
            try:
                os.remove(fname + ".old")
            except OSError:
                pass  # just protect

            # create new file
            with os.open(fname + ".new", os.O_CREAT | os.O_WRONLY, 0o600) as file:
                file.write(credential_data)

            # copy the old file to a tmp bck and rename new one to the official name
            try:
                shutil.copy2(fname, fname + ".old")
            except (OSError, shutil.Error):
                # file not found, permission error, same file
                pass  # just protect

            os.rename(fname + ".new", fname)


# Helper for process_global
def update_credential_file(username, client_id, credential_data, request_clientname):
    """
    Updates the credential file

    :param username: credentials' username
    :param client_id: id used for tracking the submit credentials
    :param credential_data: the credentials to be advertised
    :param request_clientname: client name passed by frontend
    :return:the credential file updated
    """

    proxy_dir = glideFactoryLib.factoryConfig.get_client_proxies_dir(username)
    fname_short = f"credential_{request_clientname}_{glideFactoryLib.escapeParam(client_id)}"
    fname = os.path.join(proxy_dir, fname_short)
    fname_compressed = "%s_compressed" % fname

    msg = "updating credential file %s" % fname
    logSupport.log.debug(msg)

    safe_update(fname, credential_data)
    compressed_credential = compress_credential(credential_data)
    # Compressed+encoded credentials are used for GCE and AWS and have a key=value format (glidein_credentials= ...)
    safe_update(fname_compressed, b"glidein_credentials=%s" % compressed_credential)

    return fname, fname_compressed


def get_key_obj(pub_key_obj, classad):
    """
    Gets the symmetric key object from the request classad

    @type pub_key_obj: object
    @param pub_key_obj: The factory public key object.  This contains all the encryption and decryption methods
    @type classad: dictionary
    @param classad: a dictionary representation of the classad
    """
    if "ReqEncKeyCode" in classad:
        try:
            sym_key_obj = pub_key_obj.extract_sym_key(classad["ReqEncKeyCode"])
            return sym_key_obj
        except:
            logSupport.log.debug(f"\nclassad {classad}\npub_key_obj {pub_key_obj}\n")
            error_str = "Symmetric key extraction failed."
            logSupport.log.exception(error_str)
            raise CredentialError(error_str)
    else:
        error_str = "Classad does not contain a key.  We cannot decrypt."
        raise CredentialError(error_str)


# Helper for process_global
def validate_frontend(classad, frontend_descript, pub_key_obj):
    """
    Validates that the frontend advertising the classad is allowed and that it
    claims to have the same identity that Condor thinks it has.

    @type classad: dictionary
    @param classad: a dictionary representation of the classad
    @type frontend_descript: class object
    @param frontend_descript: class object containing all the frontend information
    @type pub_key_obj: object
    @param pub_key_obj: The factory public key object.  This contains all the encryption and decryption methods

    @return: sym_key_obj - the object containing the symmetric key used for decryption
    @return: frontend_sec_name - the frontend security name, used for determining
    the username to use.
    """

    # we can get classads from multiple frontends, each with their own
    # sym keys.  So get the sym_key_obj for each classad
    sym_key_obj = get_key_obj(pub_key_obj, classad)
    authenticated_identity = classad["AuthenticatedIdentity"]

    # verify that the identity that the client claims to be is the identity that Condor thinks it is
    try:
        enc_identity = sym_key_obj.decrypt_hex(classad["ReqEncIdentity"]).decode("utf-8")
    except:
        error_str = "Cannot decrypt ReqEncIdentity."
        logSupport.log.exception(error_str)
        raise CredentialError(error_str)

    if enc_identity != authenticated_identity:
        error_str = "Client provided invalid ReqEncIdentity(%s!=%s). " "Skipping for security reasons." % (
            enc_identity,
            authenticated_identity,
        )
        raise CredentialError(error_str)
    try:
        frontend_sec_name = sym_key_obj.decrypt_hex(classad["GlideinEncParamSecurityName"]).decode("utf-8")
    except:
        error_str = "Cannot decrypt GlideinEncParamSecurityName."
        logSupport.log.exception(error_str)
        raise CredentialError(error_str)

    # verify that the frontend is authorized to talk to the factory
    expected_identity = frontend_descript.get_identity(frontend_sec_name)
    if expected_identity is None:
        error_str = "This frontend is not authorized by the factory.  Supplied security name: %s" % frontend_sec_name
        raise CredentialError(error_str)
    if authenticated_identity != expected_identity:
        error_str = "This frontend Authenticated Identity, does not match the expected identity"
        raise CredentialError(error_str)

    return sym_key_obj, frontend_sec_name


def process_global(classad, glidein_descript, frontend_descript):
    # Factory public key must exist for decryption
    pub_key_obj = glidein_descript.data["PubKeyObj"]
    if pub_key_obj is None:
        raise CredentialError("Factory has no public key.  We cannot decrypt.")

    try:
        # Get the frontend security name so that we can look up the username
        sym_key_obj, frontend_sec_name = validate_frontend(classad, frontend_descript, pub_key_obj)

        request_clientname = classad["ClientName"]

        # get all the credential ids by filtering keys by regex
        # this makes looking up specific values in the dict easier
        r = re.compile("^GlideinEncParamSecurityClass")
        mkeys = list(filter(r.match, list(classad.keys())))
        for key in mkeys:
            prefix_len = len("GlideinEncParamSecurityClass")
            cred_id = key[prefix_len:]

            cred_data = sym_key_obj.decrypt_hex(classad["GlideinEncParam%s" % cred_id])
            security_class = sym_key_obj.decrypt_hex(classad[key]).decode("utf-8")
            username = frontend_descript.get_username(frontend_sec_name, security_class)
            if username == None:
                logSupport.log.error(
                    (
                        "Cannot find a mapping for credential %s of client %s. Skipping it. The security"
                        "class field is set to %s in the frontend. Please, verify the glideinWMS.xml and"
                        " make sure it is mapped correctly"
                    )
                    % (cred_id, classad["ClientName"], security_class)
                )
                continue

            msg = "updating credential for %s" % username
            logSupport.log.debug(msg)

            update_credential_file(username, cred_id, cred_data, request_clientname)
    except:
        logSupport.log.debug(f"\nclassad {classad}\nfrontend_descript {frontend_descript}\npub_key_obj {pub_key_obj})")
        error_str = "Error occurred processing the globals classads."
        logSupport.log.exception(error_str)
        raise CredentialError(error_str)


# Not sure if this has to be abstract - probably better?
def check_security_credentials(auth_method, params, client_int_name, entry_name, scitoken_passthru=False):
    """
    Verify that only credentials for the given auth method are in the params

    Args:
        auth_method: (string): authentication method of an entry, defined in the config
        params: (dictionary): decrypted params passed in a frontend (client) request
        client_int_name (string): internal client name
        entry_name: (string): name of the entry
        scitoken_passthru: (bool): if True, scitoken present in credential. Override checks
                                for 'auth_method' and proceded with glidein request
    Raises:
    CredentialError: if the credentials in params don't match what is defined for the auth method
    """

    auth_method_list = auth_method.split("+")
    if not set(auth_method_list) & set(SUPPORTED_AUTH_METHODS):
        logSupport.log.warning(
            "None of the supported auth methods %s in provided auth methods: %s"
            % (SUPPORTED_AUTH_METHODS, auth_method_list)
        )
        return

    params_keys = set(params.keys())
    relevant_keys = {
        "SubmitProxy",
        "GlideinProxy",
        "Username",
        "Password",
        "PublicCert",
        "PrivateCert",
        "PublicKey",
        "PrivateKey",
        "VMId",
        "VMType",
        "AuthFile",
    }

    if "scitoken" in auth_method_list or "frontend_scitoken" in params and scitoken_passthru:
        # TODO  check validity
        # TODO  Specifically, Add checks that no undesired credentials are
        #       sent also when token is used
        return
    if "grid_proxy" in auth_method_list:
        if not scitoken_passthru:
            if "SubmitProxy" in params:
                # v3+ protocol
                valid_keys = {"SubmitProxy"}
                invalid_keys = relevant_keys.difference(valid_keys)
                if params_keys.intersection(invalid_keys):
                    raise CredentialError(
                        "Request from %s has credentials not required by the entry %s, skipping request"
                        % (client_int_name, entry_name)
                    )
            else:
                # No proxy sent
                raise CredentialError(
                    "Request from client %s did not provide a proxy as required by the entry %s, skipping request"
                    % (client_int_name, entry_name)
                )

    else:
        # Only v3+ protocol supports non grid entries
        # Verify that the glidein proxy was provided for non-proxy auth methods
        if "GlideinProxy" not in params and not scitoken_passthru:
            raise CredentialError("Glidein proxy cannot be found for client %s, skipping request" % client_int_name)

        if "cert_pair" in auth_method_list:
            # Validate both the public and private certs were passed
            if not (("PublicCert" in params) and ("PrivateCert" in params)):
                # if not ('PublicCert' in params and 'PrivateCert' in params):
                # cert pair is required, cannot service request
                raise CredentialError(
                    "Client '%s' did not specify the certificate pair in the request, this is required by entry %s, skipping "
                    % (client_int_name, entry_name)
                )
            # Verify no other credentials were passed
            valid_keys = {"GlideinProxy", "PublicCert", "PrivateCert", "VMId", "VMType"}
            invalid_keys = relevant_keys.difference(valid_keys)
            if params_keys.intersection(invalid_keys):
                raise CredentialError(
                    "Request from %s has credentials not required by the entry %s, skipping request"
                    % (client_int_name, entry_name)
                )

        elif "key_pair" in auth_method_list:
            # Validate both the public and private keys were passed
            if not (("PublicKey" in params) and ("PrivateKey" in params)):
                # key pair is required, cannot service request
                raise CredentialError(
                    "Client '%s' did not specify the key pair in the request, this is required by entry %s, skipping "
                    % (client_int_name, entry_name)
                )
            # Verify no other credentials were passed
            valid_keys = {"GlideinProxy", "PublicKey", "PrivateKey", "VMId", "VMType"}
            invalid_keys = relevant_keys.difference(valid_keys)
            if params_keys.intersection(invalid_keys):
                raise CredentialError(
                    "Request from %s has credentials not required by the entry %s, skipping request"
                    % (client_int_name, entry_name)
                )

        elif "auth_file" in auth_method_list:
            # Validate auth_file is passed
            if not ("AuthFile" in params):
                # auth_file is required, cannot service request
                raise CredentialError(
                    "Client '%s' did not specify the auth_file in the request, this is required by entry %s, skipping "
                    % (client_int_name, entry_name)
                )
            # Verify no other credentials were passed
            valid_keys = {"GlideinProxy", "AuthFile", "VMId", "VMType"}
            invalid_keys = relevant_keys.difference(valid_keys)
            if params_keys.intersection(invalid_keys):
                raise CredentialError(
                    "Request from %s has credentials not required by the entry %s, skipping request"
                    % (client_int_name, entry_name)
                )

        elif "username_password" in auth_method_list:
            # Validate username and password keys were passed
            if not (("Username" in params) and ("Password" in params)):
                # username and password is required, cannot service request
                raise CredentialError(
                    "Client '%s' did not specify the username and password in the request, this is required by entry %s, skipping "
                    % (client_int_name, entry_name)
                )
            # Verify no other credentials were passed
            valid_keys = {"GlideinProxy", "Username", "Password", "VMId", "VMType"}
            invalid_keys = relevant_keys.difference(valid_keys)
            if params_keys.intersection(invalid_keys):
                raise CredentialError(
                    "Request from %s has credentials not required by the entry %s, skipping request"
                    % (client_int_name, entry_name)
                )

        else:
            # should never get here, unsupported main authentication method is checked at the beginning
            raise CredentialError("Inconsistency between SUPPORTED_AUTH_METHODS and check_security_credentials")

    # No invalid credentials found
    return
