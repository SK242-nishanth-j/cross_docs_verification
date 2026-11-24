"""
File: __init__.py
Purpose: Underwriting copilot backend package.
Owner: genai-platform@shellkode
Created: 2026-11-24 | Deps: truststore

TLS is verified against the operating system certificate store, so corporate
TLS inspection (for example Zscaler) works. This runs on the first import of the
package, before any boto3 client is created.
"""

import truststore

truststore.inject_into_ssl()
