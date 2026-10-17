import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from games import create, list_games, TicTacToe, Hangman, Checkers, Chess


class GameRegistryTests(unittest.TestCase):
    def test_list_games_returns_expected(self) -> None:
        names = list_games()
        for expected in ("chess", "checkers", "hangman", "tictactoe"):
            self.assertIn(expected, names)

    def test_create_unknown_returns_none(self) -> None:
        self.assertIsNone(create("notagame"))

    def test_create_each_game(self) -> None:
        for name, cls in (("tictactoe", TicTacToe), ("ttt", TicTacToe),
                          ("hangman", Hangman), ("checkers", Checkers),
                          ("chess", Chess)):
            game = create(name)
            self.assertIsInstance(game, cls)


class TicTacToeTests(unittest.TestCase):
    def test_game_ends(self) -> None:
        game = TicTacToe()
        game.start()
        for cell in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            out = game.move(cell)
            if game.over:
                break
        self.assertTrue(game.over)

    def test_draw(self) -> None:
        game = TicTacToe()
        game.start()
        for cell in ("1", "2", "3", "4", "6", "7", "8", "5", "9"):
            out = game.move(cell)
            if game.over:
                break
        self.assertTrue(game.over)

    def test_invalid_cell_rejected(self) -> None:
        game = TicTacToe()
        game.start()
        out = game.move("99")
        self.assertIn("Invalid", out)
        self.assertFalse(game.over)


class HangmanTests(unittest.TestCase):
    def _set_word(self, game, word):
        game.start()
        game.word = word
        game.guessed = set()
        game.wrong = set()
        game.over = False

    def test_win(self) -> None:
        game = Hangman()
        self._set_word(game, "cat")
        for letter in ("c", "a", "t"):
            game.move(letter)
            if game.over:
                break
        self.assertTrue(game.over)

    def test_lose(self) -> None:
        game = Hangman()
        self._set_word(game, "zoo")
        for letter in ("a", "b", "c", "d", "e", "f", "g"):
            game.move(letter)
            if game.over:
                break
        self.assertTrue(game.over)


class CheckersTests(unittest.TestCase):
    def test_move_and_ai_responds(self) -> None:
        game = Checkers()
        game.start()
        # Red piece at compact index 20 (row 5); advance up to row 4 (index 16).
        out = game.move("20 16")
        self.assertNotIn("Illegal", out)
        self.assertFalse(game.over)

    def test_illegal_move_rejected(self) -> None:
        game = Checkers()
        game.start()
        out = game.move("20 24")  # 24 is a light square, not playable
        self.assertIn("Illegal", out)
        self.assertFalse(game.over)


class ChessTests(unittest.TestCase):
    def test_legal_move_and_ai(self) -> None:
        game = Chess()
        game.start()
        out = game.move("e2e4")
        self.assertNotIn("Illegal", out)
        self.assertFalse(game.over)

    def test_not_your_piece(self) -> None:
        game = Chess()
        game.start()
        out = game.move("e7e5")  # black piece, white turn
        self.assertIn("Not your piece", out)

    def test_bad_format_rejected(self) -> None:
        game = Chess()
        game.start()
        out = game.move("e2e")
        self.assertIn("Move as: e2e4", out)


if __name__ == "__main__":
    unittest.main()
