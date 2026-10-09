import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

# Import the test
from tests.test_resident_visitor_visibility import (
    test_event_registration_shows_success_then_already_registered,
    test_activity_registration_shows_success_then_already_registered
)

print("=" * 60)
print("Running test_event_registration_shows_success_then_already_registered...")
print("=" * 60)
try:
    test_event_registration_shows_success_then_already_registered()
    print("[PASS] test_event_registration_shows_success_then_already_registered")
except AssertionError as e:
    print("[FAIL] test_event_registration_shows_success_then_already_registered")
    print(f"AssertionError: {e}")
except Exception as e:
    print("[ERROR] test_event_registration_shows_success_then_already_registered")
    print(f"Error: {type(e).__name__}: {e}")

print("\n" + "=" * 60)
print("Running test_activity_registration_shows_success_then_already_registered...")
print("=" * 60)
try:
    test_activity_registration_shows_success_then_already_registered()
    print("[PASS] test_activity_registration_shows_success_then_already_registered")
except AssertionError as e:
    print("[FAIL] test_activity_registration_shows_success_then_already_registered")
    print(f"AssertionError: {e}")
except Exception as e:
    print("[ERROR] test_activity_registration_shows_success_then_already_registered")
    print(f"Error: {type(e).__name__}: {e}")
