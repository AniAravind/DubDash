#!/usr/bin/env python3
"""Run pytest and annotate actual test failures in GitHub Actions checks."""
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def escape(value):
    return value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def main(argv=None):
    with tempfile.TemporaryDirectory(prefix='dubdash-test-report-') as directory:
        report = Path(directory)/'results.xml'
        result = subprocess.run([sys.executable, '-m', 'pytest',
            *(sys.argv[1:] if argv is None else argv), '--junitxml='+str(report)])
        if result.returncode and report.exists():
            for case in ET.parse(report).iter('testcase'):
                for failure in [*case.findall('failure'), *case.findall('error')]:
                    title = escape(case.get('classname', '')+'.'+case.get('name', '')).replace(',', '%2C').replace(':', '%3A')
                    # GitHub truncates annotations to 4096 characters. Keep the
                    # assertion tail, rather than losing it after a long fixture.
                    detail = escape((failure.text or failure.get('message', 'Test failed'))[-3000:])
                    print(f'::error title={title}::{detail}', flush=True)
        return result.returncode


if __name__ == '__main__':
    sys.exit(main())
