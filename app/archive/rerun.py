from datetime import UTC,datetime
from time import perf_counter

from app.archive.canonical import digest
from app.clearing import Clearing
from app.setup import POLICY
from app.source.packet import decode,fingerprint


def run(docket, payload):
    started=perf_counter()
    original,source=decode(payload)
    hashes=fingerprint(original)
    clearing=Clearing(original,docket.secret)
    # 费率版本表随原件解析；非法配置在此抛错，事务不开启，旧留档原样保留。
    ratebook=clearing.ratebook.fingerprint()
    key=digest({'files':hashes,'policy':POLICY,'rates':ratebook})
    existing=docket.find(key)
    if existing:
        return existing,True
    report=clearing.report()
    manifest={'key':key,'source':source,'rule':POLICY,'inputs':hashes,'rate_versions':ratebook,
              'evidence_sha256':digest(report),
              'survey':vars(clearing.survey),'created_utc':datetime.now(UTC).isoformat(timespec='seconds'),
              'elapsed_ms':round((perf_counter()-started)*1000)}
    return docket.publish(key,{'manifest':manifest,'evidence':report})
