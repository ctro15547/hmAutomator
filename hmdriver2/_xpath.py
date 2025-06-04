# -*- coding: utf-8 -*-

import re
from typing import Dict
from lxml import etree
from functools import cached_property

from . import logger
from .proto import Bounds
from .driver import Driver
from .utils import delay, parse_bounds
from .exception import XmlElementNotFoundError


class _XPath:
    def __init__(self, d: Driver):
        self._d = d

    def __call__(self, xpath: str) -> '_XMLElement':

        hierarchy: Dict = self._d.dump_hierarchy()
        if not hierarchy:
            raise RuntimeError("hierarchy is empty")

        xml = _XPath._json2xml(hierarchy)
        result = xml.xpath(xpath)

        if len(result) > 0:
            node = result[0]
            raw_bounds: str = node.attrib.get("bounds")  # [832,1282][1125,1412]
            bounds: Bounds = parse_bounds(raw_bounds)
            logger.debug(f"{xpath} Bounds: {bounds}")
            return _XMLElement(bounds, self._d, hierarchy, xpath)

        return _XMLElement(None, self._d, hierarchy, xpath)

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """Remove XML-incompatible control characters."""
        return re.sub(r'[\x00-\x1F\x7F]', '', text)

    @staticmethod
    def _json2xml(hierarchy: Dict) -> etree.Element:
        """Convert JSON-like hierarchy to XML."""
        attributes = hierarchy.get("attributes", {})

        # 过滤所有属性的值，确保无非法字符
        cleaned_attributes = {k: _XPath._sanitize_text(str(v)) for k, v in attributes.items()}

        tag = cleaned_attributes.get("type", "orgRoot") or "orgRoot"
        xml = etree.Element(tag, attrib=cleaned_attributes)

        children = hierarchy.get("children", [])
        for item in children:
            xml.append(_XPath._json2xml(item))

        return xml


class _XMLElement:
    def __init__(self, bounds: Bounds, d: Driver, hierarchy: Dict, xpath: str):
        self.bounds = bounds
        self._d = d
        self.hierarchy = hierarchy
        self.xpath = xpath

    def info(self):
        _rename_key = {
            "checkable": "isChecked"
        }
        if not self.hierarchy or not self.xpath:
            return {}
        xml = _XPath._json2xml(self.hierarchy)
        result = xml.xpath(self.xpath)
        if len(result) > 0:
            node = result[0]
            info = dict(node.attrib)
            return_info = self._rename_keys_func(info, _rename_key)
            return return_info
        return {}
    
    def _rename_keys_func(self, info: Dict, rename_key: Dict) -> Dict:
        return {rename_key.get(k, k): v for k, v in info.items()}

    def _verify(self):
        if not self.bounds:
            raise XmlElementNotFoundError("xpath not found")

    @cached_property
    def center(self):
        self._verify()
        return self.bounds.get_center()

    def exists(self) -> bool:
        return self.bounds is not None

    @delay
    def click(self):
        x, y = self.center.x, self.center.y
        self._d.click(x, y)

    @delay
    def click_if_exists(self):

        if not self.exists():
            logger.debug("click_exist: xpath not found")
            return

        x, y = self.center.x, self.center.y
        self._d.click(x, y)

    @delay
    def double_click(self):
        x, y = self.center.x, self.center.y
        self._d.double_click(x, y)

    @delay
    def long_click(self):
        x, y = self.center.x, self.center.y
        self._d.long_click(x, y)

    @delay
    def input_text(self, text):
        self.click()
        self._d.input_text(text)