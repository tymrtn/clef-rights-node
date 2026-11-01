#!/usr/bin/env python3
"""Freeze a private, tested launch-review bundle without changing Git or deploying."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
import tempfile
import time
from verify_public_repository import find_content_issues, is_private_artifact_path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE = 8 * 1024 * 1024
MAX_SOURCE = 128 * 1024 * 1024


class PackageError(RuntimeError):
    pass


def git(root, *args):
    environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    return subprocess.run(['git', *args], cwd=root, env=environment, check=True, capture_output=True, timeout=20).stdout


def collect(root, *, generated=False):
    if Path(root).is_symlink():
        raise PackageError("Source packages require regular roots, without symlinks")
    root = Path(root).resolve()
    if generated:
        names = sorted(str(path.relative_to(root)) for path in root.rglob('*') if not path.is_dir())
    else:
        names = sorted(set(path.decode() for path in git(root, 'ls-files', '-co', '--exclude-standard', '-z').split(b'\0') if path))
    files = {}; total = 0
    for name in names:
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name:
            raise PackageError('Unsafe source path')
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue  # An intentional deletion in the working tree.
        if any((root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts)+1)):
            raise PackageError('Source packages require regular files, without symlinks')
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
            raise PackageError('Source contains an unsupported or oversized file')
        # A single generated offer PDF is part of the public website build.
        public_pdf = name in {'public/downloads/clef-partner-pack.pdf', 'downloads/clef-partner-pack.pdf'}
        if is_private_artifact_path(name) and not public_pdf:
            raise PackageError('Source contains a private artifact; preserve it outside the distributable source')
        data = path.read_bytes(); total += len(data)
        if total > MAX_SOURCE:
            raise PackageError('Source package exceeds its size limit')
        if not public_pdf and b'\x00' not in data:
            issues = find_content_issues(name, data.decode('utf8', errors='replace'))
            if issues:
                raise PackageError('Source privacy check failed: ' + ', '.join(sorted({str(issue['rule']) for issue in issues})))
        files[name] = (0o755 if info.st_mode & 0o111 else 0o644, data)
    if not files:
        raise PackageError('Source package is empty')
    return files


def inventory(files):
    return [{'path': name, 'mode': format(mode, 'o'), 'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
            for name, (mode,data) in sorted(files.items())]


def fingerprint(files):
    return hashlib.sha256(json.dumps(inventory(files),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def require_unchanged(before, after):
    if fingerprint(before) != fingerprint(after):
        raise PackageError('Source changed during verification. Re-run against the finished candidate.')


def archive_bytes(files):
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as archive:
        for name,(mode,data) in sorted(files.items()):
            item=tarfile.TarInfo(name); item.mode=mode; item.size=len(data); item.mtime=0
            archive.addfile(item,io.BytesIO(data))
    return gzip.compress(raw.getvalue(),mtime=0)


def run_check(command, root, log):
    environment = {key:value for key,value in os.environ.items() if not key.startswith(('VITE_', 'GIT_'))}
    environment.update(VITE_API_BASE='/api', VITE_DEMO_MODE='false')
    started=time.monotonic()
    with log.open('wb') as output:
        result=subprocess.run(command,cwd=root,env=environment,stdout=output,stderr=subprocess.STDOUT,timeout=1200)
    if result.returncode:
        raise PackageError(f'Verification failed ({log.name}); inspect the private build log')
    return {'command':command,'exitCode':0,'durationSeconds':round(time.monotonic()-started,2),
            'logSha256':hashlib.sha256(log.read_bytes()).hexdigest()}


def prepare(node_root, landing_root, output):
    node_root=Path(node_root).resolve(); landing_root=Path(landing_root).resolve(); output=Path(output).resolve()
    if output.exists(): raise PackageError('Choose a new output directory; existing review bundles are preserved')
    for root in (node_root,landing_root):
        if output.is_relative_to(root): raise PackageError('Place the review bundle outside either source repository')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.clef-review-',dir=output.parent) as temporary:
        stage=Path(temporary)
        try:
            before={'rights-node':collect(node_root),'website':collect(landing_root)}
            bases={name:git(root,'rev-parse','HEAD').decode().strip() for name,root in [('rights-node',node_root),('website',landing_root)]}
            checks=[run_check(['make','verify-alpha'],node_root,stage/'rights-node-checks.log'),
                    run_check(['uvx','--from','pip-audit==2.10.1','pip-audit','--require-hashes','--disable-pip','-r','backend/requirements.lock'],node_root,stage/'dependency-audit.log'),
                    run_check(['npm','run','build'],landing_root,stage/'website-checks.log')]
            after={'rights-node':collect(node_root),'website':collect(landing_root)}
            for name in before: require_unchanged(before[name],after[name])
            files={f'{name}/source/{path}':entry for name,source in after.items() for path,entry in source.items()}
            for name,root in [('rights-node',node_root/'frontend/dist'),('website',landing_root/'dist')]:
                files.update({f'{name}/web/{path}':entry for path,entry in collect(root,generated=True).items()})
            blob=archive_bytes(files)
            manifest={'schemaVersion':'clef.launch-review.v1','stage':'local-review-candidate','publicReleaseReady':False,
                'createdAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                'repositories':{name:{'baseCommit':bases[name], 'workingSourceSha256':fingerprint(after[name]),'fileCount':len(after[name])} for name in after},
                'checks':checks,'archive':{'name':'clef-review.tar.gz','sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob)},
                'files':inventory(files),
                'publicationRequirements':['Approve and commit the reviewed source; publish the exact corresponding source.',
                  'Build API, web and workers from the same adopted commit; migrate through 0021_federated_requests.',
                  'Complete the hosted synthetic tour and verify the deployed source, signing key and required worker readiness.',
                  'Publish the matching website and video correction after the sandbox acceptance.',
                  'Complete independent installation and controlled-catalog gates before claiming verified adopter readiness.']}
            (stage/'clef-review.tar.gz').write_bytes(blob)
            (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            for path in stage.iterdir(): path.chmod(0o600)
            # Install the complete bundle together, after all checks pass.
            os.rename(stage,output)
        except (PackageError, OSError, subprocess.SubprocessError) as error:
            # Keep only private diagnostic logs. A failed build cannot resemble a
            # completed candidate or leave an unsigned partial archive for review.
            for path in stage.iterdir():
                if path.is_file() and path.suffix != '.log': path.unlink()
            failure = {'schemaVersion': 'clef.launch-review.v1', 'stage': 'verification-failed',
                       'publicReleaseReady': False, 'error': str(error)}
            (stage / 'failure.json').write_text(json.dumps(failure, indent=2) + '\n')
            for path in stage.iterdir(): path.chmod(0o600)
            os.rename(stage, output)
            raise PackageError(f'Candidate verification failed; private diagnostics: {output}') from error
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--landing-root',type=Path,default=ROOT.parent/'clef-pro-landing')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    try:
        manifest=prepare(ROOT,args.landing_root,args.output)
        print(json.dumps({'ok':True,'stage':manifest['stage'],'output':str(args.output.absolute()),'archiveSha256':manifest['archive']['sha256'],'fileCount':len(manifest['files'])}))
    except (PackageError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'ok':False,'error':str(error)}))
        raise SystemExit(1)
