import logging
import shutil
import subprocess
from enum import Enum
from os import path
from typing import Any, Dict, List, Tuple

from ulauncher.api import Extension, ExtensionResult, ExtensionSmallResult
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.OpenAction import OpenAction
from ulauncher.api.shared.query import Query

logger = logging.getLogger(__name__)


class SearchType(Enum):
    BOTH = 0
    FILES = 1
    DIRS = 2


BinNames = Dict[str, str]
ExtensionPreferences = Dict[str, str]
FuzzyFinderPreferences = Dict[str, Any]


class FuzzyFinderExtension(Extension):
    @staticmethod
    def assign_bin_name(bin_names: BinNames, bin_cmd: str, testing_cmd: str) -> BinNames:
        try:
            if shutil.which(testing_cmd):
                bin_names[bin_cmd] = testing_cmd
        except subprocess.CalledProcessError:
            pass

        return bin_names

    @staticmethod
    def check_preferences(preferences: ExtensionPreferences) -> List[str]:
        logger.debug("Checking user preferences are valid")
        errors = []

        base_dir = preferences["base_dir"]
        if not path.isdir(path.expanduser(base_dir)):
            errors.append(f"Base directory '{base_dir}' is not a directory.")

        ignore_file = preferences["ignore_file"]
        if ignore_file and not path.isfile(path.expanduser(ignore_file)):
            errors.append(f"Ignore file '{ignore_file}' is not a file.")

        try:
            result_limit = int(preferences["result_limit"])
            if result_limit <= 0:
                errors.append("Result limit must be greater than 0.")
        except ValueError:
            errors.append("Result limit must be an integer.")

        if not errors:
            logger.debug("User preferences validated")

        return errors

    @staticmethod
    def get_preferences(input_preferences: ExtensionPreferences) -> FuzzyFinderPreferences:
        preferences: FuzzyFinderPreferences = {
            "search_type": SearchType(int(input_preferences["search_type"])),
            "allow_hidden": bool(int(input_preferences["allow_hidden"])),
            "result_limit": int(input_preferences["result_limit"]),
            "base_dir": path.expanduser(input_preferences["base_dir"]),
            "ignore_file": path.expanduser(input_preferences["ignore_file"]),
        }

        logger.debug("Using user preferences %s", preferences)

        return preferences

    @staticmethod
    def generate_fd_cmd(fd_bin: str, preferences: FuzzyFinderPreferences) -> List[str]:
        cmd = [fd_bin, ".", preferences["base_dir"]]
        if preferences["search_type"] == SearchType.FILES:
            cmd.extend(["--type", "f"])
        elif preferences["search_type"] == SearchType.DIRS:
            cmd.extend(["--type", "d"])

        if preferences["allow_hidden"]:
            cmd.extend(["--hidden"])

        if preferences["ignore_file"]:
            cmd.extend(["--ignore-file", preferences["ignore_file"]])

        return cmd

    def get_binaries(self) -> Tuple[BinNames, List[str]]:
        logger.debug("Checking and getting binaries for dependencies")
        bin_names: BinNames = {}
        bin_names = self.assign_bin_name(bin_names, "fzf_bin", "fzf")
        bin_names = self.assign_bin_name(bin_names, "fd_bin", "fd")
        if bin_names.get("fd_bin") is None:
            bin_names = self.assign_bin_name(bin_names, "fd_bin", "fdfind")

        errors = []
        if bin_names.get("fzf_bin") is None:
            errors.append("Missing dependency fzf. Please install fzf.")
        if bin_names.get("fd_bin") is None:
            errors.append("Missing dependency fd. Please install fd.")

        if not errors:
            logger.debug("Using binaries %s", bin_names)

        return bin_names, errors

    def search(
        self, query: str, preferences: FuzzyFinderPreferences, fd_bin: str, fzf_bin: str
    ) -> List[str]:
        logger.debug("Finding results for %s", query)

        fd_cmd = self.generate_fd_cmd(fd_bin, preferences)
        with subprocess.Popen(fd_cmd, stdout=subprocess.PIPE) as fd_proc:
            fzf_cmd = [fzf_bin, "--filter", query]
            output = subprocess.check_output(fzf_cmd, stdin=fd_proc.stdout, text=True)
            results = output.splitlines()

            limit = preferences["result_limit"]
            results = results[:limit]
            logger.info("Found results: %s", results)

            return results

    @staticmethod
    def get_dirname(filename: str) -> str:
        dirname = filename if path.isdir(filename) else path.dirname(filename)
        return dirname

    @staticmethod
    def no_op_result_items(msgs: List[str], icon: str = "icon") -> List[ExtensionResult]:
        def create_result_item(msg):
            return ExtensionResult(
                icon=f"images/{icon}.png",
                name=msg,
                on_enter=DoNothingAction(),
            )

        return list(map(create_result_item, msgs))

    def on_query_change(self, query: str, _) -> List[ExtensionResult]:
        bin_names, errors = self.get_binaries()
        errors.extend(self.check_preferences(self.preferences))
        if errors:
            return self.no_op_result_items(errors, "error")

        if not query:
            return self.no_op_result_items(["Enter your search criteria."])

        preferences = self.get_preferences(self.preferences)

        try:
            results = self.search(query, preferences, **bin_names)
        except subprocess.CalledProcessError as error:
            failing_cmd = error.cmd[0]
            if failing_cmd == "fzf" and error.returncode == 1:
                return self.no_op_result_items(["No results found."])

            logger.debug("Subprocess %s failed with status code %s", error.cmd, error.returncode)
            return self.no_op_result_items(["There was an error running this extension."], "error")

        def create_result_item(filename):
            return ExtensionSmallResult(
                icon="images/sub-icon.png",
                name=filename,
                on_enter=OpenAction(filename),
                on_alt_enter=OpenAction(self.get_dirname(filename)),
            )

        return list(map(create_result_item, results))


if __name__ == "__main__":
    FuzzyFinderExtension().run()
