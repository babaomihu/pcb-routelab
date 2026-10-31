"""Maintainer-only: bind the explicit source-only publication inventory."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
allowed_dirs=['src','docs','examples','tests','scripts','research','licenses','evidence','.github']
root_files=['LICENSE','README.md','README.zh-CN.md','THIRD_PARTY_NOTICES.md','pyproject.toml','MANIFEST.in','.gitignore','.env.example',
            'requirements.lock.txt','requirements-build.lock.txt','requirements-harness.lock.txt','source-origins.json']
def eligible(p):
 return p.is_file() and not p.is_symlink() and not any(x in ('__pycache__','target') or x.endswith('.egg-info') for x in p.parts) and p.suffix not in ('.so','.dylib','.pyd','.pyc','.kicad_prl')
files=set(root_files)
for name in allowed_dirs:
 files.update(str(p.relative_to(ROOT)) for p in (ROOT/name).rglob('*') if eligible(p))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
code={p:digest(ROOT/p) for p in sorted(files) if p.startswith(('src/','research/','tests/','scripts/'))}
(ROOT/'source-lock.json').write_text(json.dumps({'release':'0.1.0','files':code},indent=2)+'\n')
files.add('source-lock.json');files.add('release-files.json')
(ROOT/'release-files.json').write_text(json.dumps({'version':1,'files':sorted(files),'excluded':'private jobs, binaries, virtual environments, original board datasets and raw model transcripts'},indent=2)+'\n')
(ROOT/'RELEASE_FILES.sha256').write_text(''.join(digest(ROOT/p)+'  '+p+'\n' for p in sorted(files)))
print('Sealed',len(files),'files plus checksum manifest')
