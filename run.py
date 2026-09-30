"""Convenience alias for factory.py business-ktv, not a separate project."""
from tools.business_ktv.cli import main

if __name__ == '__main__':
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
