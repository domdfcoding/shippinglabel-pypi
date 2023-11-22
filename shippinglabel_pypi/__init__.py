#!/usr/bin/env python3
#
#  __init__.py
"""
Shippinglabel extension for interacting with the Python Package Index (PyPI)..

.. seealso::

	`pypi-json`_, which provides some of the functionality from this module but with a reusable HTTP session and
	support for authentication with other endpoints (such as a private package repository).

.. _pypi-json: https://pypi-json.readthedocs.io/en/latest/
"""
#
#  Copyright © 2022 Dominic Davis-Foster <dominic@davis-foster.co.uk>
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in all
#  copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
#  EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
#  MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
#  IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
#  DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
#  OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE
#  OR OTHER DEALINGS IN THE SOFTWARE.
#

# stdlib
import atexit
import pathlib
from typing import Any, Callable, Dict, List, Tuple, Union

# 3rd party
import dist_meta.distributions
import requests
from apeye.requests_url import RequestsURL
from apeye.url import URL
from dist_meta.metadata_mapping import MetadataMapping
from domdf_python_tools.paths import PathPlus
from domdf_python_tools.typing import PathLike
from packaging.requirements import InvalidRequirement
from packaging.specifiers import SpecifierSet
from packaging.tags import Tag, sys_tags
from packaging.version import Version
from pypi_json import FileURL, PyPIJSON
from shippinglabel import normalize
from shippinglabel.requirements import operator_symbols, read_requirements

__author__: str = "Dominic Davis-Foster"
__copyright__: str = "2022 Dominic Davis-Foster"
__license__: str = "MIT License"
__email__: str = "dominic@davis-foster.co.uk"

#: The version number of this extension.
__version__: str = "0.1.0.post1"

__all__ = (
		"get_project_links",
		"get_metadata",
		"get_latest",
		"bind_requirements",
		"get_pypi_releases",
		"get_releases_with_digests",
		"get_file_from_pypi",
		"get_sdist_url",
		"get_wheel_url",
		"get_wheel_tag_mapping",
		)

_session = requests.session()
atexit.register(_session.close)


class ProjectLinks(MetadataMapping):
	pass


def get_project_links(project_name: str) -> MetadataMapping:
	"""
	Returns the web links for the given project.

	The exact keys vary, but common keys include "Documentation" and "Issue Tracker".

	.. note::

		The :core-meta:`Home-Page` field from Python core metadata is included under the ``Homepage`` key, if present.
		This matches the output parsed from PyPI for packages which are not installed.

	:param project_name:
	"""

	# Try a local package first

	urls = ProjectLinks()

	try:
		dist = dist_meta.distributions.get_distribution(project_name)
		meta = dist.get_metadata()
		raw_urls = meta.get_all("Project-URL", default=())

		for url in raw_urls:
			label, url, *_ = map(str.strip, url.split(','))
			urls[label] = url  # pylint: disable=loop-invariant-statement

		if "Home-Page" in meta:
			urls["Homepage"] = meta["Home-Page"]

	except dist_meta.distributions.DistributionNotFoundError:
		# Fall back to PyPI

		metadata = get_metadata(project_name)["info"]

		if "project_urls" in metadata and metadata["project_urls"]:
			for label, url in metadata["project_urls"].items():
				urls[label] = url

	return urls


def get_metadata(pypi_name: str) -> Dict[str, Any]:
	"""
	Returns metadata for the given project on PyPI.

	:param pypi_name:

	:raises:

		* :exc:`packaging.requirements.InvalidRequirement` if the project cannot be found on PyPI.
		* :exc:`requests.HTTPError` if an error occurs when communicating with PyPI.
	"""

	with PyPIJSON(session=_session) as client:
		return client.get_metadata(pypi_name)._asdict()


def get_latest(pypi_name: str) -> str:
	"""
	Returns the version number of the latest release on PyPI for the given project.

	:param pypi_name:

	:raises:

		* :exc:`packaging.requirements.InvalidRequirement` if the project cannot be found on PyPI.
		* :exc:`requests.HTTPError` if an error occurs when communicating with PyPI.
	"""

	return str(get_metadata(pypi_name)["info"]["version"])


def bind_requirements(
		filename: PathLike,
		specifier: str = ">=",
		normalize_func: Callable[[str], str] = normalize,
		) -> int:
	"""
	Bind unbound requirements in the given file to the latest version on PyPI, and any later versions.

	:param filename: The requirements.txt file to bind requirements in.
	:param specifier: The requirement specifier symbol to use.
	:param normalize_func: Function to use to normalize the names of requirements.

	:return: ``1`` if the file was changed; ``0`` otherwise.
	"""

	if specifier not in operator_symbols:
		raise ValueError(f"Invalid specifier {specifier!r}")

	ret = 0
	filename = PathPlus(filename)
	requirements, comments, invalid_lines = read_requirements(
		filename,
		include_invalid=True,
		normalize_func=normalize_func,
		)

	for req in requirements:
		if req.url:
			continue

		if not req.specifier:
			ret |= 1
			req.specifier = SpecifierSet(f"{specifier}{get_latest(req.name)}")

	sorted_requirements = sorted(requirements)

	buf: List[str] = [*comments, *invalid_lines, *(str(req) for req in sorted_requirements)]

	if buf != list(filter(lambda x: x != '', filename.read_lines())):
		ret |= 1
		filename.write_lines(buf)

	return ret


def get_pypi_releases(pypi_name: str) -> Dict[str, List[str]]:
	"""
	Returns a dictionary mapping PyPI release versions to download URLs.

	:param pypi_name: The name of the project on PyPI.

	:raises:

		* :exc:`packaging.requirements.InvalidRequirement` if the project cannot be found on PyPI.
		* :exc:`requests.HTTPError` if an error occurs when communicating with PyPI.
	"""

	with PyPIJSON(session=_session) as client:
		return client.get_metadata(pypi_name).get_releases()


def get_releases_with_digests(pypi_name: str) -> Dict[str, List[FileURL]]:
	"""
	Returns a dictionary mapping PyPI release versions to download URLs and the sha256sum of the file contents.

	:param pypi_name: The name of the project on PyPI.

	:raises:

		* :exc:`packaging.requirements.InvalidRequirement` if the project cannot be found on PyPI.
		* :exc:`requests.HTTPError` if an error occurs when communicating with PyPI.
	"""

	with PyPIJSON(session=_session) as client:
		metadata = client.get_metadata(pypi_name)

	return metadata.get_releases_with_digests()


def get_file_from_pypi(url: Union[URL, str], tmpdir: PathLike) -> None:
	"""
	Download the file with the given URL into the given (temporary) directory.

	:param url: The URL to download the file from.
	:param tmpdir: The (temporary) directory to store the downloaded file in.
	"""

	should_close = False

	if not isinstance(url, RequestsURL):
		url = RequestsURL(url)
		should_close = True

	filename = url.name

	r = url.get()
	if r.status_code != 200:  # pragma: no cover
		raise OSError(f"Unable to download '{filename}' from PyPI.")

	(pathlib.Path(tmpdir) / filename).write_bytes(r.content)

	if should_close:
		url.session.close()


def get_sdist_url(
		name: str,
		version: Union[str, int, Version],
		strict: bool = False,
		) -> str:
	"""
	Returns the URL of the project's source distribution on PyPI.

	:param name: The name of the project on PyPI.
	:param version:
	:param strict: Causes a :exc:`ValueError` to be raised if no sdist is found,
		rather than retuning a wheel.

	.. attention::

		If no source distribution is found this function may return a wheel or "zip" sdist
		unless ``strict`` is :py:obj:`True`.
	"""

	releases = get_pypi_releases(str(name))
	version = str(version)

	if version not in releases:
		raise InvalidRequirement(f"Cannot find version {version} on PyPI.")

	download_urls = releases[version]

	if not download_urls:
		raise ValueError(f"Version {version} has no files on PyPI.")

	for url in download_urls:
		if url.endswith(".tar.gz"):
			return url

	if strict:
		raise ValueError(f"Version {version} has no sdist on PyPI.")

	for url in download_urls:
		if url.endswith(".zip"):
			return url

	return download_urls[0]


def get_wheel_url(
		name: str,
		version: Union[str, int, Version],
		strict: bool = False,
		) -> str:
	"""
	Returns the URL of one of the project's wheels on PyPI.

	For finer control over which wheel the URL is for see the :func:`~.get_wheel_tag_mapping` function.

	:param name: The name of the project on PyPI.
	:param version:
	:param strict: Causes a :exc:`ValueError` to be raised if no wheels are found,
		rather than retuning a wheel.

	.. attention::

		If no wheels are found this function may return an sdist
		unless ``strict`` is :py:obj:`True`.
	"""

	tag_url_map, non_wheel_urls = get_wheel_tag_mapping(name, version)

	for tag in sys_tags():
		if tag in tag_url_map:
			return str(tag_url_map[tag])

	if strict:
		raise ValueError(f"Version {version} has no wheels on PyPI.")
	elif not non_wheel_urls:  # pragma: no cover
		raise ValueError(f"Version {version} has no files on PyPI.")
	else:
		return str(non_wheel_urls[0])


def get_wheel_tag_mapping(
		name: str,
		version: Union[str, int, Version],
		) -> Tuple[Dict[Tag, URL], List[URL]]:
	"""
	Constructs a mapping of wheel tags to the PyPI download URL of the wheel with relevant tag.

	This can be used alongside :func:`packaging.tags.sys_tags` to select the best wheel for the current platform.

	:param name: The name of the project on PyPI.
	:param version:

	:returns: A tuple containing the ``tag: url`` mapping,
		and a list of download URLs for non-wheel artifacts (e.g. sdists).
	"""

	with PyPIJSON(session=_session) as client:
		return client.get_metadata(name).get_wheel_tag_mapping(version)
