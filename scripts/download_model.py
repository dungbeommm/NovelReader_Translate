"""Download a translation model into models/translation/."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translation.engines import LocalEngine, MODELS

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=MODELS, default='HachimiMT-60-QT')
    parser.add_argument('--smoke', action='store_true', help='Dịch thử một câu sau khi nạp model.')
    args=parser.parse_args()
    engine=LocalEngine(args.model)
    engine.load()
    print('Đã nạp model:',args.model)
    if args.smoke:
        print(engine.translate(['你好。'], {}))

if __name__ == '__main__':
    main()
