import os
import re
import tarfile
from typing import Iterable

from huggingface_hub import cached_assets_path

from datatrove.data import Document
from datatrove.utils._import_utils import ASSETS_PATH

from ..writers.disk_base import DiskWriter
from .base_filter import BaseFilter


normalizer = re.compile(r"[^a-zA-Z0-9]+")


def normalize(text, replace=""):
    return normalizer.sub(replace, text).lower()


def parse_list(line, do_normalize=True):
    return {normalize(x) if do_normalize else x.strip() for x in line if x[0] != "#"}


def get_list(abs_path: str, file_name: str, extra: set = None, do_normalize: bool = True):
    with open(os.path.join(abs_path, file_name)) as f:
        return parse_list(f, do_normalize).union(set(parse_list(extra, do_normalize)) if extra else set())


class URLFilter(BaseFilter):
    name = "😈 Url-filter"
    _requires_dependencies = ["tldextract"]

    def __init__(
        self,
        soft_word_threshold: int = 2,
        extra_domains: Iterable = None,
        extra_urls: Iterable = None,
        banned_words: Iterable = None,
        banned_subwords: Iterable = None,
        soft_banned_words: Iterable = None,
        exclusion_writer: DiskWriter = None,
    ):
        from tldextract import TLDExtract

        super().__init__(exclusion_writer)
        self.soft_word_threshold = soft_word_threshold
        self.block_listed_domains = extra_domains
        self.block_listed_url = extra_urls
        self.banned_words = banned_words
        self.banned_subwords = banned_subwords
        self.soft_banned_words = soft_banned_words
        self._downloaded = False
        self.tldextractor = TLDExtract()

    def download_data(self):
        if self._downloaded:
            return
        download_dir = cached_assets_path(library_name="datatrove", namespace="filters", subfolder="url_filter")
        if not os.path.isfile(os.path.join(download_dir, "adult", "domains")) or not os.path.isfile(
            os.path.join(download_dir, "adult", "urls")
        ):
            with tarfile.open(os.path.join(ASSETS_PATH, "url_filterblacklists.tar.gz"), "r:gz") as tar:
                tar.extractall(download_dir)
        self.block_listed_domains = get_list(
            download_dir, "adult/domains", self.block_listed_domains, do_normalize=False
        )
        self.block_listed_url = get_list(download_dir, "adult/urls", self.block_listed_url, do_normalize=False)
        self.banned_words = get_list(ASSETS_PATH, "banned_words.txt", self.banned_words)
        self.banned_subwords = get_list(ASSETS_PATH, "banned_subwords.txt", self.banned_subwords)
        self.soft_banned_words = get_list(ASSETS_PATH, "soft_banned_words.txt", self.soft_banned_words)
        self._downloaded = True

    def filter(self, document: Document) -> bool | tuple[bool, str]:
        self.download_data()
        url = document.metadata.get("url")

        assert url, "Document does not have url in its metadata"
        url_info = self.tldextractor(url)

        if url_info.registered_domain in self.block_listed_domains:
            return False, "domain"

        if url_info.fqdn in self.block_listed_domains:
            return False, "subdomain"

        if url in self.block_listed_url:
            return False, "url"

        url_words = set(normalizer.split(url))
        if any(word in url_words for word in self.banned_words):
            return False, "hard_blacklisted"

        nb_soft_words = sum([word in url_words for word in self.soft_banned_words])
        if nb_soft_words >= self.soft_word_threshold:
            return False, "soft_blacklisted"

        normalized_space = normalize(url)
        if any(word in normalized_space for word in self.banned_subwords):
            return False, "blacklisted_subword"

        return True
