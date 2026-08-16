import collections
import json
import time
import urllib.request

UA={"User-Agent":"TraceTriage-recon/0.1 (kesavk659@gmail.com)"}
url="https://network.satnogs.org/api/observations/?format=json&end=2026-07-15T00:00:00Z"
tot=collections.Counter(); st=collections.Counter(); wf=0; cm=0; tle=0; n=0
stations=set(); tx=set(); norad=set(); clients=collections.Counter()
pages=0
while url and pages<24:
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=60) as r:
        d=json.loads(r.read()); link=r.headers.get("Link","")
    for o in d:
        n+=1
        tot[o.get("waterfall_status")]+=1
        st[o.get("status")]+=1
        if o.get("waterfall"): wf+=1
        if o.get("client_metadata"): cm+=1
        if o.get("tle1") and o.get("tle2"): tle+=1
        stations.add(o.get("ground_station")); tx.add(o.get("transmitter_uuid")); norad.add(o.get("norad_cat_id"))
        clients[o.get("client_version","")[:12]]+=1
    pages+=1
    url=None
    for part in link.split(","):
        if 'rel="next"' in part: url=part.split(";")[0].strip().strip("<>")
    time.sleep(0.4)
print("pages",pages,"records",n)
print("waterfall_status:",dict(tot))
print("status:",dict(st))
print(f"waterfall url present: {wf}/{n} = {wf/n:.1%}")
print(f"client_metadata present: {cm}/{n} = {cm/n:.1%}")
print(f"tle1+tle2 present: {tle}/{n} = {tle/n:.1%}")
dec=tot['with-signal']+tot['without-signal']
print(f"DECISIVE waterfall labels: {dec}/{n} = {dec/n:.1%}")
print("unique stations",len(stations),"unique transmitters",len(tx),"unique norad",len(norad))
print("client_version top:",clients.most_common(6))
