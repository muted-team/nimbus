"""The open client resolves streamed TikTok geography without private modules."""
import unittest
from unittest.mock import Mock, patch

from curl_cffi import requests
from modules import client_device, proxy_pool


class ProxyCountryTests(unittest.TestCase):
    def test_streamed_country_is_read_without_profiles_private_regex(self):
        response = Mock()
        response.iter_content.return_value = [b'<html>{"reg', b'ion" : "US"}</html>']
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value = response
        with client_device.use_browser_profile("chrome152"), patch.object(requests, "Session", return_value=session):
            self.assertEqual(proxy_pool._country_probe("http://fixture:synthetic@proxy.invalid:6969"), "US")
        response.close.assert_called_once()
        session.get.assert_called_once()

    def test_missing_country_or_bounded_stream_stays_unknown(self):
        for chunks in ([b'<html>no profile region</html>'],
                       [b'x' * (proxy_pool.COUNTRY_MAX_BYTES + 1), b'"region":"US"']):
            with self.subTest(chunks_count=len(chunks)):
                response = Mock()
                response.iter_content.return_value = chunks
                session = Mock()
                session.__enter__ = Mock(return_value=session)
                session.__exit__ = Mock(return_value=False)
                session.get.return_value = response
                with client_device.use_browser_profile("chrome152"), patch.object(requests, "Session", return_value=session):
                    self.assertEqual(proxy_pool._country_probe("http://proxy.invalid:6969"), "")
                response.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
