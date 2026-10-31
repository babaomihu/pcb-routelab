"""Read-only release allowlist, checksums, private-path and secret-pattern audit."""
import argparse,hashlib,json,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));a=p.parse_args();root=Path(a.root).resolve()
manifest=json.loads((root/'release-files.json').read_text())
paths=manifest['files'];failures=[]
for rel in paths:
 path=root/rel
 if not path.is_file() or path.is_symlink():failures.append({'path':rel,'reason':'missing or symlink'});continue
 if not path.resolve().is_relative_to(root):failures.append({'path':rel,'reason':'outside release root'});continue
 if any(x in path.parts for x in ('__pycache__','.venv','runs','target')) or path.suffix in ('.so','.dylib','.pyd','.pyc','.kicad_prl'):
  failures.append({'path':rel,'reason':'runtime/binary in source release'})
 raw=path.read_bytes()
 try:text=raw.decode('utf-8')
 except UnicodeDecodeError:failures.append({'path':rel,'reason':'unexpected binary'});continue
 if re.search(re.escape('/'+'Users/')+r'(?!\{)[^/\s]+/',text):failures.append({'path':rel,'reason':'private absolute user path'})
 # Report filenames only. Never print a matched value.
 if re.search(r'(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)',text):
  failures.append({'path':rel,'reason':'possible credential'})
 if re.search(r'"api_key"\s*:\s*"(?!\s*")(?!test-only-placeholder)[^"]{12,}"',text):
  failures.append({'path':rel,'reason':'populated key config'})
checksums={}
for line in (root/'RELEASE_FILES.sha256').read_text().splitlines():
 digest,rel=line.split('  ',1);checksums[rel]=digest
if set(checksums)!=set(paths):failures.append({'reason':'checksum/allowlist mismatch'})
for rel,h in checksums.items():
 p=root/rel
 if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()!=h:failures.append({'path':rel,'reason':'checksum mismatch'})
lock=json.loads((root/'source-lock.json').read_text())
for rel,h in lock['files'].items():
 if not (root/rel).is_file() or hashlib.sha256((root/rel).read_bytes()).hexdigest()!=h:failures.append({'path':rel,'reason':'source lock mismatch'})
origins=json.loads((root/'source-origins.json').read_text())
for item in origins['files']:
 path=root/item['path']
 if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['released_sha256']:
  failures.append({'path':item['path'],'reason':'released provenance hash mismatch'})
print(json.dumps({'passed':not failures,'files':len(paths),'source_files':len(lock['files']),'failures':failures,'model_requests':0},ensure_ascii=False,indent=2))
raise SystemExit(1 if failures else 0)
