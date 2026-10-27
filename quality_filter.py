"""Explicit source-quality exclusions established without reserved-test model scores."""
import argparse
import hashlib
import json
from pathlib import Path
import predictor as base

EXCLUDED = {('openfootball:en.1','2019-20'):
 'Source dates 66 July 2020 fixtures as July 2019; exclude entire affected league-season'}
EVIDENCE='https://www.premierleague.com/en/news/1697163/match-summary-afc-bournemouth-v-newcastle-united'


def filter_rows(rows):
    return [r for r in rows if (r['competition_id'],r['season']) not in EXCLUDED]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();rows=base.load(args.source);clean=filter_rows(rows)
    args.output.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in clean),encoding='utf8')
    report=dict(input=str(args.source),input_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
        output=str(args.output),output_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
        input_matches=len(rows),output_matches=len(clean),excluded=len(rows)-len(clean),
        rules=[dict(competition=c,season=s,reason=why) for (c,s),why in EXCLUDED.items()],
        independent_evidence=EVIDENCE,selection_basis='source quality; no reserved-test performance used')
    args.output.with_suffix('.quality.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
