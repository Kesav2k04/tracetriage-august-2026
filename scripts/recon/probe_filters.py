import collections
import json
import urllib.request

B="https://network.satnogs.org/api/observations/?format=json"
def get(q,n=1):
    req=urllib.request.Request(B+q,headers={"User-Agent":"TraceTriage-recon/0.1 (kesavk659@gmail.com)"})
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.loads(r.read()),dict(r.headers)
tests={
 "status=good":"&status=good",
 "waterfall_status=with-signal":"&waterfall_status=with-signal",
 "waterfall_status=without-signal":"&waterfall_status=without-signal",
 "vetted_status=good":"&vetted_status=good",
 "ground_station=2937":"&ground_station=2937",
 "satellite__norad_cat_id=25544":"&satellite__norad_cat_id=25544",
 "transmitter_mode=BPSK":"&transmitter_mode=BPSK",
 "start=2026-08-01":"&start=2026-08-01T00:00:00Z",
 "end=2026-08-05":"&end=2026-08-05T00:00:00Z",
}
for name,q in tests.items():
    try:
        d,h=get(q)
        if not d: print(f"{name:34s} -> 0 records"); continue
        key=name.split("=")[0]
        vals=collections.Counter(str(r.get(key.split("__")[0] if "__" not in key else "norad_cat_id"))for r in d)
        st=collections.Counter(r["status"] for r in d)
        ws=collections.Counter(r["waterfall_status"] for r in d)
        wf=sum(1 for r in d if r.get("waterfall"))
        print(f"{name:34s} -> n={len(d)} status={dict(st)} wf_status={dict(ws)} waterfall_urls={wf}")
    except Exception as e:
        print(f"{name:34s} -> ERROR {type(e).__name__}: {str(e)[:90]}")
