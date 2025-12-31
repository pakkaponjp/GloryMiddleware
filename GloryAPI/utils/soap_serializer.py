#
# File: GloryAPI/utils/soap_serializer.py
# Author: Pakkapon Jirachatmongkon
# Date: July 25, 2025
# Description: Utility functions for serializing Zeep objects and pretty-printing XML.
#
# License: P POWER GENERATING CO.,LTD.
#
# Usage: Imported by SOAP client to handle data serialization and XML formatting.
#
from lxml import etree
from zeep.helpers import serialize_object

def serialize_zeep_object(obj):
    """
    Serializes a Zeep object (response from SOAP call) into a Python-native dictionary/list structure.
    This makes the Zeep response easier to work with and convert to JSON.

    Args:
        obj: The Zeep object to serialize.

    Returns:
        A dictionary or list representing the serialized Zeep object.
    """
    return serialize_object(obj)

def pretty_print_xml(xml_element):
    """
    Pretty-prints an lxml ElementTree object into a human-readable XML string.

    Args:
        xml_element: The lxml.etree._Element object to print.

    Returns:
        A formatted XML string.
    """
    return etree.tostring(xml_element, pretty_print=True, encoding='unicode')
