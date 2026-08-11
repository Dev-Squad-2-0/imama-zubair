"""Smoke test: verify email parsing works and customer email is forwarded"""
import sys, os
sys.path.insert(0, 'src')
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

# 1. Test email parsing from speech
from conversation_memory import parse_email_address

cases = [
    ("imamazubair@gmail.com", "imamazubair@gmail.com"),
    ("meri email hai imamazubair8@gmail.com theek hai", "imamazubair8@gmail.com"),
    ("imamazubair at gmail dot com", "imamazubair@gmail.com"),
    ("send it to test.user at yahoo dot pk", "test.user@yahoo.pk"),
    ("no email here, just a number 03001234567", None),
]

print("=== Email parsing tests ===")
all_ok = True
for text, expected in cases:
    result = parse_email_address(text)
    ok = result == expected
    status = "✓" if ok else "✗"
    if not ok: all_ok = False
    print(f"  {status}  Input: '{text[:40]}...' -> {result!r} (expected {expected!r})")

print(f"\nAll tests passed: {all_ok}")

# 2. Test the state.py email slot threading
from state import slots_from_text
profile = {"client_name": "Ahmed", "client_phone": "03001227540", "client_email": None}
prefs = {}
result = slots_from_text(profile, prefs, 0, "ji meri email hai imamazubair@gmail.com")
print(f"\nSlot extraction result: client_email={result['user_profile'].get('client_email')!r}")
