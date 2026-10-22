"""Console UI for setup command."""


def printable(text: str) -> str:
    """Escape non-printable characters so file-derived text cannot drive the terminal."""
    return "".join(ch if ch.isprintable() else ch.encode("unicode_escape").decode("ascii") for ch in text)


class ConsoleUI:
    """Interactive console UI for setup command."""

    def confirm(self, message: str) -> bool:
        """Ask user for yes/no confirmation.

        Default is no (returns False for empty input).
        """
        response = input(f"{message} [y/N] ").strip().lower()
        return response in ("y", "yes")

    def choose(self, message: str, options: list[str]) -> int:
        """Ask user to choose from options.

        Returns 0-based index of selected option.
        """
        print(message)
        for i, option in enumerate(options, 1):
            print(f"{i}. {option}")

        while True:
            try:
                choice = int(input("Your choice: ").strip())
                if 1 <= choice <= len(options):
                    return choice - 1
            except ValueError:
                pass
            print(f"Please enter a number between 1 and {len(options)}")
