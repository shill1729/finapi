import os
import base64
import nacl.signing


def update_keypair() -> None:
    """
    Generates an Ed25519 keypair for use with the Robinhood Crypto API.

    Returns:
        (private_key_b64, public_key_b64): Both keys base64-encoded.
        Submit the public key to Robinhood; store the private key as ROBINHOOD_API_KEY.
    """
    private_key = nacl.signing.SigningKey.generate()
    public_key = private_key.verify_key

    private_key_b64 = base64.b64encode(private_key.encode()).decode()
    public_key_b64 = base64.b64encode(public_key.encode()).decode()
    os.environ["ROBINHOOD_API_KEY"] = private_key_b64
    os.environ["ROBINHOOD_PUBLIC_KEY"] = public_key_b64
    return None


if __name__ == "__main__":
    update_keypair()
    print("Keys updated")
