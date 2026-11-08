"""Run an identical controlled context workload against a selected source checkout.

Use --source-root for the baseline; fixtures and contract implementation remain fixed.
Byte counts are serialized request-envelope bytes, not measured provider tokens.
"""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--operator-root',type=Path,default=Path('../operator_sandbox'))
    parser.add_argument('--compact-at',type=int,default=100000)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    fixture_root=Path(__file__).resolve().parent.parent
    operator=args.operator_root.resolve();source=args.source_root.resolve();output=args.output.resolve()
    sys.path[:0]=[str(source/'src'),str(operator/'contracts/python'),str(fixture_root/'tests')]
    os.chdir(source)  # Use the selected version's exact privileged prompt.
    from operator_contracts import Protocol
    from context_overhead_fixture import measure
    result=measure(Protocol(operator/'schemas'),operator/'schemas',args.compact_at)
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='requests'},indent=2))


if __name__=='__main__':main()
