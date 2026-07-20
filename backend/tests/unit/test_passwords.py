from app.infrastructure.auth.passwords import hash_password, verify_password


def test_argon2_password_round_trip() -> None:
    encoded = hash_password("correct horse battery staple")

    assert encoded.startswith("$argon2")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)
