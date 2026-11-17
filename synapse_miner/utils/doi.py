"""DOI forms: the bare DOI for matching, and the link written to the portal tables."""

import math
import re

# Prefixes around a bare DOI: doi.org links in any form (www., dx., http)
# and "doi:"
_DOI_PREFIX = re.compile(r"^(https?://(www\.|dx\.)?doi\.org/|doi:\s*)", re.I)


def bare_doi(value) -> str:
    """The DOI itself (e.g. 10.1158/1078-0432.CCR-24-3029), without any link or "doi:" prefix."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return _DOI_PREFIX.sub("", str(value).strip())
