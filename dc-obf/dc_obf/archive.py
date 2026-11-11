"""Durable private jobs, independent of release updates and Discord CDN URLs."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from .config import private_write


class Job:
    def __init__(self, filename, interaction_id):
        root = Path.home() / '.local/share/dc-obf/jobs'
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        root.chmod(0o700)
        self.id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
        self.directory = root / self.id
        self.directory.mkdir(mode=0o700)
        self.source = self.directory / 'input.lua'
        self.output = self.directory / 'protected.lua'
        self.data = {'job_id': self.id, 'filename': filename, 'interaction_id': str(interaction_id),
                     'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'receiving'}
        self.record()

    def record(self, **fields):
        self.data.update(fields)
        self.data['updated_at'] = datetime.now(timezone.utc).isoformat()
        private_write(self.directory / 'job.json', json.dumps(self.data, ensure_ascii=False) + '\n')

    def save_source(self, content):
        with self.source.open('xb') as stream:
            self.source.chmod(0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        self.record(status='received', source_bytes=len(content), source_sha256=hashlib.sha256(content).hexdigest())

    def finish_output(self):
        self.output.chmod(0o600)
        with self.output.open('rb') as stream:
            os.fsync(stream.fileno())
        self.record(status='transformed', output_bytes=self.output.stat().st_size,
                    output_sha256=hashlib.sha256(self.output.read_bytes()).hexdigest())
