# -*- coding: utf-8 -*-
"""
Module that implements the questions types
"""

import json
import os
import errno
import sys

from . import errors


def question_factory(kind, *args, **kwargs):
    for clazz in (Text, Editor, Password, Confirm, List, Checkbox, Path):
        if clazz.kind == kind:
            return clazz(*args, **kwargs)
    raise errors.UnknownQuestionTypeError()


def load_from_dict(question_dict):
    """
    Load one question from a dict.
    It requires the keys 'name' and 'kind'.
    :return: The Question object with associated data.
    :return type: Question
    """
    return question_factory(**question_dict)


def load_from_list(question_list):
    """
    Load a list of questions from a list of dicts.
    It requires the keys 'name' and 'kind' for each dict.
    :return: A list of Question objects with associated data.
    :return type: List
    """
    return [load_from_dict(q) for q in question_list]


def load_from_json(question_json):
    """
    Load Questions from a JSON string.
    :return: A list of Question objects with associated data if the JSON
             contains a list or a Question if the JSON contains a dict.
    :return type: List or Dict
    """
    data = json.loads(question_json)
    if isinstance(data, list):
        return load_from_list(data)
    if isinstance(data, dict):
        return load_from_dict(data)
    raise TypeError("Json contained a %s variable when a dict or list was expected", type(data))


class TaggedValue(object):
    def __init__(self, label, value):
        self.label = label
        self.value = value

    def __str__(self):
        return self.label

    def __repr__(self):
        return self.value

    def __eq__(self, other):
        if isinstance(other, TaggedValue):
            return self.value == other.value
        return self.value == other

    def __ne__(self, other):
        return not self.__eq__(other)


class Question(object):
    kind = "base question"

    def __init__(self, name, message="", choices=None, default=None, ignore=False, validate=True, show_default=False):
        self.name = name
        self._message = message
        self._choices = choices or []
        self._default = default
        self._ignore = ignore
        self._validate = validate
        self.answers = {}
        self.show_default = show_default

    @property
    def ignore(self):
        return bool(self._solve(self._ignore))

    @property
    def message(self):
        return self._solve(self._message)

    @property
    def default(self):
        return self.answers.get(self.name) or self._solve(self._default)

    @property
    def choices_generator(self):
        for choice in self._solve(self._choices):
            yield (TaggedValue(*choice) if isinstance(choice, tuple) and len(choice) == 2 else choice)

    @property
    def choices(self):
        return list(self.choices_generator)

    def validate(self, current):
        try:
            if self._solve(self._validate, current):
                return
        except errors.ValidationError as e:
            raise e
        except Exception:
            pass
        raise errors.ValidationError(current)

    def _solve(self, prop, *args, **kwargs):
        if callable(prop):
            return prop(self.answers, *args, **kwargs)
        if isinstance(prop, str):
            return prop.format(**self.answers)
        return prop


class Text(Question):
    kind = "text"

    def __init__(self, name, message="", default=None, **kwargs):
        super(Text, self).__init__(
            name, message=message, default=str(default) if default and not callable(default) else default, **kwargs
        )


class Password(Text):
    kind = "password"

    def __init__(self, name, echo="*", **kwargs):
        super(Password, self).__init__(name, **kwargs)
        self.echo = echo


class Editor(Text):
    kind = "editor"


class Confirm(Question):
    kind = "confirm"

    def __init__(self, name, default=False, **kwargs):
        super(Confirm, self).__init__(name, default=default, **kwargs)


class List(Question):
    kind = "list"

    def __init__(self, name, message="", choices=None, default=None, ignore=False, validate=True, carousel=False):

        super(List, self).__init__(name, message, choices, default, ignore, validate)
        self.carousel = carousel


class Checkbox(Question):
    kind = "checkbox"


# Solution for checking valid path based on
# https://stackoverflow.com/a/34102855/1360532
ERROR_INVALID_NAME = 123


def is_pathname_valid(pathname):
    """
    `True` if the passed pathname is a valid pathname for the current OS;
    `False` otherwise.
    """
    try:
        if not isinstance(pathname, str) or not pathname:
            return False

        _, pathname = os.path.splitdrive(pathname)

        root_dirname = os.environ.get("HOMEDRIVE", "C:") if sys.platform == "win32" else os.path.sep

        assert os.path.isdir(root_dirname)
        root_dirname = root_dirname.rstrip(os.path.sep) + os.path.sep

        for pathname_part in pathname.split(os.path.sep):
            try:
                os.lstat(root_dirname + pathname_part)
            except OSError as exc:
                if hasattr(exc, "winerror"):
                    if exc.winerror == ERROR_INVALID_NAME:
                        return False
                elif exc.errno in {errno.ENAMETOOLONG, errno.ERANGE}:
                    return False
    except (ValueError, TypeError):
        return False
    else:
        return True


class Path(Text):
    ANY = "any"
    FILE = "file"
    DIRECTORY = "directory"

    kind = "path"

    def __init__(self, name, default=None, path_type="any", exists=None, normalize_to_absolute_path=False, **kwargs):
        super(Path, self).__init__(name, default=default, **kwargs)

        self._path_type = path_type
        self._exists = exists
        self._normalize_to_absolute_path = normalize_to_absolute_path

        if default is not None:
            try:
                self.validate(default)
            except errors.ValidationError:
                raise ValueError("Default value '{}' is not valid based on " "your Path's criteria".format(default))

    def validate(self, current):
        super(Path, self).validate(current)

        if current is None:
            raise errors.ValidationError(current)

        current = self.normalize_value(current)

        if not is_pathname_valid(current):
            raise errors.ValidationError(current)

        # os.path.isdir and isfile check also existence of the path,
        # which might not be desirable
        if self._path_type == "file":
            if self._exists is None and os.path.basename(current) == "":
                raise errors.ValidationError(current)
            elif self._exists and not os.path.isfile(current):
                raise errors.ValidationError(current)
            elif self._exists is not None and not self._exists and os.path.isfile(current):
                raise errors.ValidationError(current)

        elif self._path_type == "directory":
            if self._exists is None and os.path.basename(current) != "":
                raise errors.ValidationError(current)
            elif self._exists and not os.path.isdir(current):
                raise errors.ValidationError(current)
            elif self._exists is not None and not self._exists and os.path.isdir(current):
                raise errors.ValidationError(current)

        elif self._exists and not os.path.exists(current):
            raise errors.ValidationError(current)
        elif self._exists is not None and not self._exists and os.path.exists(current):
            raise errors.ValidationError(current)

    def normalize_value(self, value):
        value = os.path.expanduser(value)

        if self._normalize_to_absolute_path:
            value = os.path.abspath(value)

        return value
