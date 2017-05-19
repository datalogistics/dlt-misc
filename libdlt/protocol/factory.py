import json

import libdlt.protocol.ibp.factory as ibp
import libdlt.protocol.ceph.factory as ceph
from lace import logging
from lace.logging import trace
from libdlt.protocol.ibp.allocation import IBP_EXTENT_URI
from libdlt.protocol.ceph.allocation import CEPH_EXTENT_URI

from unis.models import Extent

PROTOCOL_MAP = {
    "ceph": ceph,
    "ibp": ibp
}

SCHEMA_MAP = {
    CEPH_EXTENT_URI: ceph,
    IBP_EXTENT_URI: ibp
}

@trace.info("factory")
def buildAllocation(json):
    if type(json) is str:
        try:
            json = json.loads(json)
        except Exception as exp:
            logging.getLogger().warn("{func:>20}| Could not decode allocation - {exp}".format(func = "buildAllocation", exp = exp))
            return False

    if isinstance(json, Extent):
        schema = getattr(json, "$schema")
    else:
        schema = json["schema"]
    return SCHEMA_MAP[schema].buildAllocation(json)

@trace.info("factory")
def makeAllocation(data, offset, depot, **kwds):
    return PROTOCOL_MAP[depot.scheme].makeAllocation(data, offset, depot, **kwds)
