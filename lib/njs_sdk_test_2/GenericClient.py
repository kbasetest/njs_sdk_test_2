import time
import json as _json

import requests as _requests
from urllib import parse as _urlparse
import random as _random
import base64 as _base64
from configparser import ConfigParser as _ConfigParser
import os as _os

_CT = 'content-type'
_AJ = 'application/json'
_URL_SCHEME = frozenset(['http', 'https'])


def _get_token(user_id, password,
               auth_svc='https://nexus.api.globusonline.org/goauth/token?' +
                        'grant_type=client_credentials'):
    # This is bandaid helper function until we get a full
    # KBase python auth client released
    auth = _base64.b64encode(user_id + ':' + password)
    headers = {'Authorization': 'Basic ' + auth}
    ret = _requests.get(auth_svc, headers=headers, allow_redirects=True)
    status = ret.status_code
    if status >= 200 and status <= 299:
        tok = _json.loads(ret.text)
    elif status == 403:
        raise Exception('Authentication failed: Bad user_id/password ' +
                        'combination for user %s' % (user_id))
    else:
        raise Exception(ret.text)
    return tok['access_token']


def _read_rcfile(file=_os.environ['HOME'] + '/.authrc'):  # @ReservedAssignment
    # Another bandaid to read in the ~/.authrc file if one is present
    authdata = None
    if _os.path.exists(file):
        try:
            with open(file) as authrc:
                rawdata = _json.load(authrc)
                # strip down whatever we read to only what is legit
                authdata = {x: rawdata.get(x) for x in (
                    'user_id', 'token', 'client_secret', 'keyfile',
                    'keyfile_passphrase', 'password')}
        except Exception as e:
            print("Error while reading authrc file %s: %s" % (file, e))
    return authdata


def _read_inifile(file=_os.environ.get(  # @ReservedAssignment
                  'KB_DEPLOYMENT_CONFIG', _os.environ['HOME'] +
                  '/.kbase_config')):
    # Another bandaid to read in the ~/.kbase_config file if one is present
    authdata = None
    if _os.path.exists(file):
        try:
            config = _ConfigParser()
            config.read(file)
            # strip down whatever we read to only what is legit
            authdata = {x: config.get('authentication', x)
                        if config.has_option('authentication', x)
                        else None for x in ('user_id', 'token',
                                            'client_secret', 'keyfile',
                                            'keyfile_passphrase', 'password')}
        except Exception as e:
            print("Error while reading INI file %s: %s" % (file, e))
    return authdata


class ServerError(Exception):

    def __init__(self, name, code, message, data=None, error=None):
        super(Exception, self).__init__(message)
        self.name = name
        self.code = code
        self.message = '' if message is None else message
        self.data = data or error or ''
        # data = JSON RPC 2.0, error = 1.1

    def __str__(self):
        return self.name + ': ' + str(self.code) + '. ' + self.message + \
            '\n' + self.data


class _JSONObjectEncoder(_json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, frozenset):
            return list(obj)
        return _json.JSONEncoder.default(self, obj)


class GenericClient(object):

    def __init__(self, url=None, timeout=30 * 60, user_id=None,
                 password=None, token=None, ignore_authrc=False,
                 trust_all_ssl_certificates=False,
                 use_url_lookup=True,
                 async_job_check_time_ms=5000):
        if url is None:
            raise ValueError('A url is required')
        scheme, _, _, _, _, _ = _urlparse.urlparse(url)
        if scheme not in _URL_SCHEME:
            raise ValueError(url + " isn't a valid http url")
        self.url = url
        self.timeout = int(timeout)
        self._headers = dict()
        self.trust_all_ssl_certificates = trust_all_ssl_certificates
        self.use_url_lookup = use_url_lookup
        self.async_job_check_time = async_job_check_time_ms / 1000.0
        # token overrides user_id and password
        if token is not None:
            self._headers['AUTHORIZATION'] = token
        elif user_id is not None and password is not None:
            self._headers['AUTHORIZATION'] = _get_token(user_id, password)
        elif 'KB_AUTH_TOKEN' in _os.environ:
            self._headers['AUTHORIZATION'] = _os.environ.get('KB_AUTH_TOKEN')
        elif not ignore_authrc:
            authdata = _read_inifile()
            if authdata is None:
                authdata = _read_rcfile()
            if authdata is not None:
                if authdata.get('token') is not None:
                    self._headers['AUTHORIZATION'] = authdata['token']
                elif(authdata.get('user_id') is not None
                     and authdata.get('password') is not None):
                    self._headers['AUTHORIZATION'] = _get_token(
                        authdata['user_id'], authdata['password'])
        if self.timeout < 1:
            raise ValueError('Timeout value must be at least 1 second')

    def _call(self, url, method, params, json_rpc_context=None):
        if json_rpc_context and type(json_rpc_context) is not dict:
            raise ValueError('Method send_data: argument json_rpc_context is not type dict as required.')
        arg_hash = {'method': method,
                    'params': params,
                    'version': '1.1',
                    'id': str(_random.random())[2:]
                    }
        if json_rpc_context:
            arg_hash['context'] = json_rpc_context

        body = _json.dumps(arg_hash, cls=_JSONObjectEncoder)
        ret = _requests.post(url, data=body, headers=self._headers,
                             timeout=self.timeout,
                             verify=not self.trust_all_ssl_certificates)
        if ret.status_code == _requests.codes.server_error:
            json_header = None
            if _CT in ret.headers:
                json_header = ret.headers[_CT]
            if _CT in ret.headers and ret.headers[_CT] == _AJ:
                err = _json.loads(ret.text)
                if 'error' in err:
                    raise ServerError(**err['error'])
                else:
                    raise ServerError('Unknown', 0, ret.text)
            else:
                raise ServerError('Unknown', 0, ret.text)
        if ret.status_code != _requests.codes.OK:
            ret.raise_for_status()
        ret.encoding = 'utf-8'
        resp = _json.loads(ret.text)
        if 'result' not in resp:
            raise ServerError('Unknown', 0, 'An unknown server error occurred')
        return resp['result']

    def sync_call(self, service_method, param_list, service_version=None,
                  json_rpc_context=None):
        url = self.url
        if self.use_url_lookup:
            module_name = service_method.split('.')[0]
            service_status_ret = self._call(
                self.url, 'ServiceWizard.get_service_status',
                [{'module_name': module_name,
                  'version': service_version}], None)[0]
            url = service_status_ret['url']
        if service_version:
            if not json_rpc_context:
                json_rpc_context = {}
            json_rpc_context['service_ver'] = service_version
        return self._call(url, service_method, param_list, json_rpc_context)

    def _asynchronous_call_async(self, service_method, params,
                                 service_version=None, json_rpc_context=None):
        mod, meth = service_method.split('.')
        if service_version:
            if not json_rpc_context:
                json_rpc_context = {}
            json_rpc_context['service_ver'] = service_version
        return self._call(self.url, mod + '._' + meth + '_submit',
                          params, json_rpc_context)[0]

    def _asynchronous_call_check(self, service_method, job_id):
        mod, _ = service_method.split('.')
        resp = self._call(self.url, mod + '._check_job', [job_id])
        return resp[0]

    def asynchronous_call(self, service_method, params,
                          service_version=None, json_rpc_context=None):
        job_id = self._asynchronous_call_async(
            service_method, params, service_version, json_rpc_context)
        print('got job id ' + job_id)
        while True:
            time.sleep(self.async_job_check_time)
            print(str(time.time()) + " Generic client checking job state")
            job_state = self._asynchronous_call_check(service_method, job_id)
            if job_state['finished']:
                return job_state['result']
