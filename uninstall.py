#!/usr/bin/env python3
import json, shutil
from pathlib import Path
root=Path('.').resolve(); sp=root/'.claude'/'settings.json'
if sp.exists():
    s=json.loads(sp.read_text(encoding='utf-8'))
    for event, groups in list((s.get('hooks') or {}).items()):
        kept=[]
        for g in groups:
            hs=[h for h in g.get('hooks',[]) if 'agent-integrity-runtime' not in h.get('command','')]
            if hs:
                g['hooks']=hs; kept.append(g)
        s['hooks'][event]=kept
    sp.write_text(json.dumps(s,indent=2)+'\n',encoding='utf-8')
shutil.rmtree(root/'.claude'/'integrity',ignore_errors=True)
try: (root/'.claude'/'rules'/'agent-integrity.md').unlink()
except FileNotFoundError: pass
print('Agent Integrity Runtime removed. Runtime history in .ai-integrity/ was left intact.')
