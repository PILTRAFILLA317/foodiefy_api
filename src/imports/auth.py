import threading
import time
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt

from .models import JobError


class JWTVerifier:
    def __init__(self, config):
        self.config = config
        self.keys, self.loaded, self.last_fetch = {}, 0.0, 0.0
        self.lock = threading.Lock()
        self.issuer = (config.SUPABASE_URL or '').rstrip('/') + '/auth/v1'

    def configured(self):
        u = urlsplit(self.config.SUPABASE_URL or '')
        return bool(u.hostname and not u.username and not u.password and (u.scheme == 'https' or
                    self.config.APP_ENV == 'local' and u.scheme == 'http' and u.hostname in {'localhost','127.0.0.1','::1'}))

    def _key(self, kid, alg):
        with self.lock:
            now = time.monotonic()
            if now - self.loaded > 300 or kid not in self.keys:
                if now - self.last_fetch < 5:
                    raise JobError('unauthorized', 401)
                self.last_fetch = now
                try:
                    with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
                        with client.stream('GET', self.issuer + '/.well-known/jwks.json') as response:
                            response.raise_for_status()
                            body = b''
                            for part in response.iter_bytes():
                                body += part
                                if len(body) > 65536:
                                    raise ValueError('jwks_limit')
                    import json
                    keys = json.loads(body)['keys']
                    self.keys = {k['kid']: jwt.PyJWK.from_dict(k) for k in keys if k.get('kty') in {'RSA','EC'} and k.get('use','sig') == 'sig'}
                    self.loaded = now
                except Exception:
                    raise JobError('auth_unavailable', 503) from None
            key = self.keys.get(kid)
            if key is None or key.algorithm_name != alg:
                raise JobError('unauthorized', 401)
            return key.key

    def ready(self):
        if not self.configured():
            return False
        if self.config.APP_ENV == 'local' and self.config.SUPABASE_JWT_SECRET:
            return True
        if time.monotonic()-self.loaded > 300 or not self.keys:
            try:
                self._key(None, 'ES256')
            except JobError:
                pass
        return bool(self.keys and time.monotonic()-self.loaded <= 300)

    def verify(self, authorization):
        if not self.configured():
            raise JobError('auth_unavailable', 503)
        if not authorization or not authorization.startswith('Bearer ') or len(authorization) > 16384:
            raise JobError('unauthorized', 401)
        token = authorization[7:]
        try:
            # Header only selects a key from our fixed trusted JWKS; no claims are trusted here.
            header = jwt.get_unverified_header(token)
            alg = header.get('alg')
            if alg == 'HS256' and self.config.APP_ENV == 'local' and self.config.SUPABASE_JWT_SECRET:
                key = self.config.SUPABASE_JWT_SECRET.get_secret_value()
            elif alg in {'ES256','RS256'} and isinstance(header.get('kid'), str):
                key = self._key(header['kid'], alg)
            else:
                raise JobError('unauthorized', 401)
            claims = jwt.decode(token, key, algorithms=[alg], issuer=self.issuer,
                                audience=self.config.SUPABASE_JWT_AUDIENCE,
                                options={'require':['exp','iat','sub','iss','aud']}, leeway=0)
            if claims.get('role') != 'authenticated' or claims.get('is_anonymous') is True:
                raise JobError('unauthorized', 401)
            return UUID(claims['sub'])
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise JobError('unauthorized', 401) from None
