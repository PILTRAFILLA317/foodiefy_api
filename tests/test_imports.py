import json
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import SecretStr

from scripts.generate_import_contract import files
from src.config import Settings
from src.fastapi_app import create_app
from src.imports.auth import JWTVerifier
from src.imports.models import ImportRequest, JobError


def config(**kw):
    return Settings(SUPABASE_URL='https://test.supabase.co',**kw)


def token(key, user, **changes):
    claims={'sub':str(user),'aud':'authenticated','iss':'https://test.supabase.co/auth/v1','exp':int(time.time())+60,
            'iat':int(time.time()),'role':'authenticated'}
    claims.update(changes)
    return jwt.encode(claims,key,algorithm='ES256',headers={'kid':'key-1'})


def verifier():
    key=ec.generate_private_key(ec.SECP256R1())
    v=JWTVerifier(config())
    v.keys={'key-1':jwt.PyJWK.from_json(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))}
    v.loaded=time.monotonic()
    return v,key


def test_verified_sub_and_not_user_metadata():
    v,key=verifier()
    owner=uuid4()
    assert v.verify('Bearer '+token(key,owner,user_metadata={'sub':str(uuid4()),'role':'service_role'}))==owner


@pytest.mark.parametrize('change',[{'exp':1},{'aud':'wrong'},{'iss':'https://evil.example'},{'role':'service_role'},{'is_anonymous':True}])
def test_bad_claims_rejected(change):
    v,key=verifier()
    with pytest.raises(JobError,match='unauthorized'):
        v.verify('Bearer '+token(key,uuid4(),**change))


def test_signature_and_algorithm_confusion_rejected():
    v,key=verifier()
    other=ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(JobError,match='unauthorized'):
        v.verify('Bearer '+token(other,uuid4()))
    unsigned=jwt.encode({'sub':str(uuid4())},key='',algorithm='none')
    with pytest.raises(JobError,match='unauthorized'):
        v.verify('Bearer '+unsigned)


def test_jwks_rotation_refresh_uses_only_configured_endpoint(monkeypatch):
    import httpx
    key=ec.generate_private_key(ec.SECP256R1())
    public=json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    public.update(kid='key-1',alg='ES256',use='sig')
    urls=[]
    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200,json={'keys':[public]})
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler)))
    v=JWTVerifier(config())
    owner=uuid4()
    assert v.verify('Bearer '+token(key,owner))==owner
    assert len(urls)==1 and urls[0]=='https://test.supabase.co/auth/v1/.well-known/jwks.json'
    assert v.verify('Bearer '+token(key,owner))==owner
    assert len(urls)==1
    rotated=ec.generate_private_key(ec.SECP256R1())
    public.update(json.loads(jwt.algorithms.ECAlgorithm.to_jwk(rotated.public_key())))
    public['kid']='key-2'
    new=jwt.encode({'sub':str(owner),'aud':'authenticated','iss':v.issuer,'iat':int(time.time()),'exp':int(time.time())+60,'role':'authenticated'},rotated,algorithm='ES256',headers={'kid':'key-2'})
    v.last_fetch=0
    assert v.verify('Bearer '+new)==owner and len(urls)==2


def test_prod_hs256_not_accepted_and_readiness_controlled():
    cfg=config(APP_ENV='production',SUPABASE_JWT_SECRET=SecretStr('local-only-test-key'*3))
    v=JWTVerifier(cfg)
    with pytest.raises(JobError,match='unauthorized'):
        v.verify('Bearer '+jwt.encode({'sub':str(uuid4())},'local-only-test-key'*3,algorithm='HS256'))
    with TestClient(create_app(Settings())) as client:
        assert client.get('/health/live').status_code==200
        assert client.get('/health/ready').status_code==503
        assert client.post('/v1/imports',json={'url':'https://example.org'}).status_code==503


def test_contract_only_stage_no_fake_percentage():
    schema=json.loads(files()['imports.v1.schema.json'])
    assert schema['progress']=='stage_only_no_percentage'
    assert schema['endpoints']['create']['required_header']=='Idempotency-Key'


@pytest.mark.parametrize('url',['file:///etc/passwd','http://user:password@example.org','https://example.org:8443'])
def test_url_shape_rejected_without_dns(url):
    with pytest.raises(ValueError):
        ImportRequest(url=url)


def test_pasted_description_contract_stays_separate_and_bounded():
    from pydantic import ValidationError

    from src.acquisition.models import EvidenceBundle, Fragment
    from src.analysis.evidence import payload_for
    from src.analysis.models import RecipeEvidence
    text='Ingredientes: 15 g sal. Mezclar.'
    request=ImportRequest(description=text)
    assert request.url is None
    with pytest.raises(ValidationError):
        ImportRequest()
    with pytest.raises(ValidationError):
        ImportRequest(description='á'*3001)
    with pytest.raises(ValidationError):
        ImportRequest(description='  ')
    bundle=EvidenceBundle(canonical_url='',platform=None,source_type='pasted_text',description=Fragment(source_kind='description',text=text,original_chars=len(text)))
    data,_=payload_for(RecipeEvidence(bundle),20000)
    assert data['description']==text and data['transcript'] is None
    assert data['source']['source_kind']=='manual' and data['source']['url'] is None and data['source']['platform'] is None
