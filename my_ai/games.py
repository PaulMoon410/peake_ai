"""Text-based games Harold can play with the user.

Each game keeps its own in-memory session state. Games are started with
``/game <name>`` and played by typing moves directly. Only one game is
active at a time; starting a new game replaces the current one.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------


@dataclass
class GameState:
    """Snapshot a game can render for the user."""

    board: str
    prompt: str
    over: bool = False
    result: str = ""


class Game:
    """A single two-player (user vs Harold) session."""

    name: str = "game"
    user_symbol: str = "You"
    ai_symbol: str = "Harold"

    def start(self) -> str:
        raise NotImplementedError

    def move(self, text: str) -> str:
        """Apply a user move and return the rendered state."""
        raise NotImplementedError

    def render(self) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Tic-tac-toe
# ---------------------------------------------------------------------------


class TicTacToe(Game):
    name = "tictactoe"

    def __init__(self) -> None:
        self.board: list[str] = [" "] * 9
        self.turn: str = "X"  # user is X
        self.winner: Optional[str] = None
        self.over = False

    def start(self) -> str:
        self.board = [" "] * 9
        self.turn = "X"
        self.winner = None
        self.over = False
        return self.render() + "\nYou are X. Harold is O. Go first: pick a cell 1-9."

    def _win(self, b: list[str], p: str) -> bool:
        lines = (
            (0, 1, 2), (3, 4, 5), (6, 7, 8),
            (0, 3, 6), (1, 4, 7), (2, 5, 8),
            (0, 4, 8), (2, 4, 6),
        )
        return any(all(b[i] == p for i in line) for line in lines)

    def _full(self, b: list[str]) -> bool:
        return all(c != " " for c in b)

    def _ai_move(self) -> None:
        empties = [i for i, c in enumerate(self.board) if c == " "]
        if not empties:
            return
        # Win if possible.
        for i in empties:
            trial = self.board.copy()
            trial[i] = "O"
            if self._win(trial, "O"):
                self.board[i] = "O"
                return
        # Block user win.
        for i in empties:
            trial = self.board.copy()
            trial[i] = "X"
            if self._win(trial, "X"):
                self.board[i] = "O"
                return
        # Prefer center, then corners, then sides.
        for i in (4, 0, 2, 6, 8, 1, 3, 5, 7):
            if i in empties:
                self.board[i] = "O"
                return

    def move(self, text: str) -> str:
        text = text.strip()
        if self.over:
            return "Game over. Start a new game with /game tictactoe."
        try:
            cell = int(text) - 1
        except ValueError:
            return "Pick a cell 1-9."
        if cell < 0 or cell > 8 or self.board[cell] != " ":
            return "Invalid cell. Pick an empty cell 1-9."
        self.board[cell] = "X"
        if self._win(self.board, "X"):
            self.winner = "X"
            self.over = True
            return self.render() + "\nYou win!"
        if self._full(self.board):
            self.over = True
            return self.render() + "\nDraw."
        self._ai_move()
        if self._win(self.board, "O"):
            self.winner = "O"
            self.over = True
            return self.render() + "\nHarold wins."
        if self._full(self.board):
            self.over = True
            return self.render() + "\nDraw."
        return self.render()

    def render(self) -> str:
        b = self.board
        lines = []
        for r in range(3):
            row = [str(i + 1) if b[i] == " " else b[i] for i in range(r * 3, r * 3 + 3)]
            lines.append(" " + " | ".join(row) + " ")
            if r < 2:
                lines.append("---+---+---")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hangman
# ---------------------------------------------------------------------------


class Hangman(Game):
    name = "hangman"

    WORDS = (
        "python", "programming", "keyboard", "internet", "algorithm",
        "memory", "reflection", "curator", "lexicon", "discovery",
        "assistant", "blockchain", "recall", "synthesis", "terminal",
    )

    def __init__(self) -> None:
        self.word: str = ""
        self.guessed: set[str] = set()
        self.wrong: set[str] = set()
        self.max_wrong = 6
        self.over = False

    def start(self) -> str:
        self.word = random.choice(self.WORDS)
        self.guessed = set()
        self.wrong = set()
        self.over = False
        return (
            "Hangman! Guess the word, one letter at a time.\n"
            + self.render()
            + "\nMisses left: 6"
        )

    def move(self, text: str) -> str:
        text = text.strip().lower()
        if self.over:
            return "Game over. Start a new game with /game hangman."
        if len(text) != 1 or not text.isalpha():
            return "Guess a single letter."
        if text in self.guessed or text in self.wrong:
            return f"You already tried '{text}'."
        if text in self.word:
            self.guessed.add(text)
        else:
            self.wrong.add(text)
        return self.render()

    def render(self) -> str:
        shown = "".join(c if c in self.guessed else "_" for c in self.word)
        body = (
            "  +---+\n  |   |\n  O   |\n /|\\  |\n / \\  |\n      |\n========="
        )
        stages = [
            "  +---+\n      |\n      |\n      |\n      |\n      |\n=========",
            "  +---+\n  |   |\n      |\n      |\n      |\n      |\n=========",
            "  +---+\n  |   |\n  O   |\n      |\n      |\n      |\n=========",
            "  +---+\n  |   |\n  O   |\n  |   |\n      |\n      |\n=========",
            "  +---+\n  |   |\n  O   |\n /|\\  |\n      |\n      |\n=========",
            "  +---+\n  |   |\n  O   |\n /|\\  |\n /    |\n      |\n=========",
            body,
        ]
        idx = min(len(self.wrong), len(stages) - 1)
        missed = ", ".join(sorted(self.wrong)) or "none"
        over = False
        result = ""
        if set(self.word) <= self.guessed:
            over = True
            result = f"You win! The word was '{self.word}'."
        elif len(self.wrong) >= self.max_wrong:
            over = True
            result = f"You lose. The word was '{self.word}'."
        self.over = over
        return (
            f"{stages[idx]}\nWord: {shown}\n"
            f"Misses ({len(self.wrong)}/6): {missed}\n{result}".strip()
        )


# ---------------------------------------------------------------------------
# Checkers
# ---------------------------------------------------------------------------


class Checkers(Game):
    name = "checkers"

    def __init__(self) -> None:
        self.board: list[Optional[str]] = [None] * 32
        self.turn: str = "r"  # user red = lowercase, harold black = uppercase
        self.over = False
        self.winner: Optional[str] = None

    def start(self) -> str:
        # Compact 8x8 checkers, dark squares only, 12 pieces each.
        self.board = [None] * 32
        # Index mapping: compact index -> (row, col)
        for i in range(32):
            row = i // 4
            # dark squares offset alternates
            col = (i % 4) * 2 + (row % 2)
            if row < 3:
                self.board[i] = "b"  # black at top (Harold)
            elif row > 4:
                self.board[i] = "r"  # red at bottom (user)
        self.turn = "r"
        self.over = False
        self.winner = None
        return "Checkers! You are red (r, bottom). Harold is black (B, top).\n" + self.render() + "\nYour move: from to (e.g. '20 24')."

    def _sq(self, row: int, col: int) -> int:
        return row * 4 + (col // 2)

    def _pieces(self, color: str) -> list[int]:
        return [i for i, p in enumerate(self.board) if p is not None and p.lower() == color]

    def _moves_for(self, idx: int) -> list[tuple[int, int, Optional[int]]]:
        """Return list of (to, captured_idx_or_None)."""
        piece = self.board[idx]
        if piece is None:
            return []
        king = piece.isupper()
        color = piece.lower()
        row = idx // 4
        col = (idx % 4) * 2 + (row % 2)
        results: list[tuple[int, int, Optional[int]]] = []
        dirs = []
        if color == "r":
            dirs = [(-1, -1), (-1, 1)]  # red moves up (row decreases)
        else:
            dirs = [(1, -1), (1, 1)]  # black moves down
        if king:
            dirs += [(-d[0], -d[1]) for d in dirs]
        for dr, dc in dirs:
            nr, nc = row + dr, col + dc
            if 0 <= nr < 8 and 0 <= nc < 8:
                nidx = self._sq(nr, nc)
                if self.board[nidx] is None:
                    results.append((nidx, None))
                else:
                    jumped = self.board[nidx]
                    if jumped is not None and jumped.lower() != color:
                        jr, jc = nr + dr, nc + dc
                        if 0 <= jr < 8 and 0 <= jc < 8:
                            jidx = self._sq(jr, jc)
                            if self.board[jidx] is None:
                                results.append((jidx, nidx))
        return results

    def _all_moves(self, color: str) -> list[tuple[int, int, Optional[int]]]:
        moves: list[tuple[int, int, Optional[int]]] = []
        captures: list[tuple[int, int, Optional[int]]] = []
        for idx in self._pieces(color):
            for to, cap in self._moves_for(idx):
                if cap is not None:
                    captures.append((idx, to, cap))
                else:
                    moves.append((idx, to, cap))
        return captures if captures else moves

    def move(self, text: str) -> str:
        text = text.strip()
        if self.over:
            return "Game over. Start a new game with /game checkers."
        parts = text.split()
        if len(parts) != 2:
            return "Move as: from to (compact squares 0-31)."
        try:
            frm, to = int(parts[0]), int(parts[1])
        except ValueError:
            return "Move as: from to (compact squares 0-31)."
        if not (0 <= frm < 32 and 0 <= to < 32):
            return "Squares must be 0-31."
        piece = self.board[frm]
        if piece is None or piece.lower() != self.turn:
            return "Not your piece or wrong turn."
        legal = self._all_moves(self.turn)
        chosen = None
        for m_frm, m_to, m_cap in legal:
            if m_frm == frm and m_to == to:
                chosen = (m_frm, m_to, m_cap)
                break
        if chosen is None:
            return "Illegal move."
        _, to_idx, cap = chosen
        self.board[to_idx] = piece
        self.board[frm] = None
        if cap is not None:
            self.board[cap] = None
        # King promotion.
        to_row = to_idx // 4
        if piece == "r" and to_row == 0:
            self.board[to_idx] = "R"
        elif piece == "b" and to_row == 7:
            self.board[to_idx] = "B"
        # Check game over.
        opp = "b" if self.turn == "r" else "r"
        if not self._pieces(opp) or not self._all_moves(opp):
            self.over = True
            self.winner = self.turn
            return self.render() + f"\n{self.user_symbol if self.turn == 'r' else self.ai_symbol} wins!"
        self.turn = opp
        # Harold's turn.
        ai_moves = self._all_moves("b")
        if ai_moves:
            frm_a, to_a, cap_a = random.choice(ai_moves)
            self.board[to_a] = self.board[frm_a]
            self.board[frm_a] = None
            if cap_a is not None:
                self.board[cap_a] = None
            to_row = to_a // 4
            if self.board[to_a] == "b" and to_row == 7:
                self.board[to_a] = "B"
            opp2 = "r"
            if not self._pieces(opp2) or not self._all_moves(opp2):
                self.over = True
                self.winner = "b"
                return self.render() + "\nHarold wins."
            self.turn = opp2
        return self.render()

    def render(self) -> str:
        rows = []
        for row in range(8):
            line = []
            for col in range(8):
                if (row + col) % 2 == 1:
                    line.append(" . ")
                else:
                    idx = self._sq(row, col)
                    p = self.board[idx]
                    line.append(f" {p or ' '} ")
            rows.append(f"{row} " + "".join(line))
        return "\n".join(rows)


# ---------------------------------------------------------------------------
# Chess (simplified)
# ---------------------------------------------------------------------------


_PIECE_LETTERS = {
    "r": "R", "n": "N", "b": "B", "q": "Q", "k": "K", "p": "P",
}


class Chess(Game):
    name = "chess"

    def __init__(self) -> None:
        self.board: list[Optional[str]] = [None] * 64
        self.turn: str = "w"  # user white (lowercase), harold black (uppercase)
        self.over = False
        self.winner: Optional[str] = None
        self.setup()

    def setup(self) -> None:
        order = ["r", "n", "b", "q", "k", "b", "n", "r"]
        for c in range(8):
            self.board[c] = order[c].upper()  # black back rank (uppercase)
            self.board[8 + c] = "P"  # black pawns (uppercase)
            self.board[48 + c] = "p"  # white pawns (lowercase)
            self.board[56 + c] = order[c]  # white back rank (lowercase)

    def start(self) -> str:
        self.setup()
        self.turn = "w"
        self.over = False
        self.winner = None
        return "Chess! You are white (lowercase). Harold is black (uppercase).\n" + self.render() + "\nMove as: e2e4."

    def _rc(self, sq: int) -> tuple[int, int]:
        return divmod(sq, 8)

    def _sq(self, r: int, c: int) -> int:
        return r * 8 + c

    def _on(self, r: int, c: int) -> bool:
        return 0 <= r < 8 and 0 <= c < 8

    def _color(self, sq: int) -> Optional[str]:
        p = self.board[sq]
        if p is None:
            return None
        return "w" if p.islower() else "b"

    def _piece_at(self, r: int, c: int) -> Optional[str]:
        if not self._on(r, c):
            return None
        return self.board[self._sq(r, c)]

    def _moves_for(self, sq: int) -> list[int]:
        p = self.board[sq]
        if p is None:
            return []
        kind = p.lower()
        color = self._color(sq)
        r, c = self._rc(sq)
        sign = -1 if color == "w" else 1
        moves: list[int] = []
        if kind == "p":
            # forward
            nr = r + sign
            if self._on(nr, c) and self.board[self._sq(nr, c)] is None:
                moves.append(self._sq(nr, c))
                nr2 = r + 2 * sign
                start = 6 if color == "w" else 1
                if r == start and self.board[self._sq(nr2, c)] is None:
                    moves.append(self._sq(nr2, c))
            # captures
            for dc in (-1, 1):
                nr, nc = r + sign, c + dc
                if self._on(nr, nc):
                    t = self.board[self._sq(nr, nc)]
                    if t is not None and self._color(self._sq(nr, nc)) != color:
                        moves.append(self._sq(nr, nc))
        elif kind == "n":
            for dr, dc in ((2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2)):
                nr, nc = r + dr, c + dc
                if self._on(nr, nc):
                    t = self.board[self._sq(nr, nc)]
                    if t is None or self._color(self._sq(nr, nc)) != color:
                        moves.append(self._sq(nr, nc))
        elif kind == "b":
            moves.extend(self._slide(sq, r, c, ((1, 1), (1, -1), (-1, 1), (-1, -1)), color))
        elif kind == "r":
            moves.extend(self._slide(sq, r, c, ((1, 0), (-1, 0), (0, 1), (0, -1)), color))
        elif kind == "q":
            moves.extend(self._slide(sq, r, c, ((1, 1), (1, -1), (-1, 1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1)), color))
        elif kind == "k":
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if self._on(nr, nc):
                        t = self.board[self._sq(nr, nc)]
                        if t is None or self._color(self._sq(nr, nc)) != color:
                            moves.append(self._sq(nr, nc))
        return moves

    def _slide(self, sq: int, r: int, c: int, dirs, color: str) -> list[int]:
        moves: list[int] = []
        for dr, dc in dirs:
            nr, nc = r + dr, c + dc
            while self._on(nr, nc):
                t = self.board[self._sq(nr, nc)]
                if t is None:
                    moves.append(self._sq(nr, nc))
                else:
                    if self._color(self._sq(nr, nc)) != color:
                        moves.append(self._sq(nr, nc))
                    break
                nr += dr
                nc += dc
        return moves

    def _king_square(self, color: str) -> int:
        target = "k" if color == "w" else "K"
        for i, p in enumerate(self.board):
            if p == target:
                return i
        return -1

    def _in_check(self, color: str) -> bool:
        ksq = self._king_square(color)
        if ksq < 0:
            return True
        opp = "b" if color == "w" else "w"
        for i, p in enumerate(self.board):
            if p is not None and self._color(i) == opp:
                if ksq in self._moves_for(i):
                    return True
        return False

    def _legal_moves(self, color: str) -> list[tuple[int, int]]:
        legal: list[tuple[int, int]] = []
        for frm in range(64):
            p = self.board[frm]
            if p is None or self._color(frm) != color:
                continue
            for to in self._moves_for(frm):
                saved = self.board[to]
                self.board[to] = self.board[frm]
                self.board[frm] = None
                ok = not self._in_check(color)
                self.board[frm] = self.board[to]
                self.board[to] = saved
                if ok:
                    legal.append((frm, to))
        return legal

    def _san(self, sq: int) -> str:
        r, c = self._rc(sq)
        return f"{chr(ord('a') + c)}{8 - r}"

    def move(self, text: str) -> str:
        text = text.strip().lower()
        if self.over:
            return "Game over. Start a new game with /game chess."
        if (len(text) != 4 or text[0] not in "abcdefgh" or text[1] not in "12345678"
                or text[2] not in "abcdefgh" or text[3] not in "12345678"):
            return "Move as: e2e4 (algebraic)."
        c1, r1 = ord(text[0]) - ord("a"), 8 - int(text[1])
        c2, r2 = ord(text[2]) - ord("a"), 8 - int(text[3])
        if not (self._on(r1, c1) and self._on(r2, c2)):
            return "Off the board."
        frm, to = self._sq(r1, c1), self._sq(r2, c2)
        piece = self.board[frm]
        if piece is None or self._color(frm) != self.turn:
            return "Not your piece."
        legal = self._legal_moves(self.turn)
        if (frm, to) not in legal:
            return "Illegal move."
        captured = self.board[to]
        self.board[to] = piece
        self.board[frm] = None
        # Pawn promotion to queen.
        kind = piece.lower()
        to_row = to // 8
        if kind == "p" and (to_row == 0 or to_row == 7):
            self.board[to] = "q" if self.turn == "w" else "Q"
        opp = "b" if self.turn == "w" else "w"
        opp_legal = self._legal_moves(opp)
        detail = ""
        if captured:
            detail = f" (captured {_PIECE_LETTERS[captured.lower()]})"
        if not opp_legal:
            self.over = True
            self.winner = self.turn
            if self._in_check(opp):
                return self.render() + f"\nCheckmate! {self.user_symbol if self.turn == 'w' else self.ai_symbol} wins.{detail}"
            return self.render() + f"\nStalemate. Draw.{detail}"
        if self._in_check(opp):
            detail = " Check!" + detail
        self.turn = opp
        # Harold's move.
        ai_legal = self._legal_moves("b")
        if ai_legal:
            afrm, ato = random.choice(ai_legal)
            acap = self.board[ato]
            apiece = self.board[afrm]
            self.board[ato] = apiece
            self.board[afrm] = None
            if apiece.lower() == "p" and ato // 8 == 0:
                self.board[ato] = "q"
            detail_ai = f" (captured {_PIECE_LETTERS[acap.lower()]})" if acap else ""
            my_legal = self._legal_moves("w")
            if not my_legal:
                self.over = True
                self.winner = "b"
                if self._in_check("w"):
                    return self.render() + f"\nHarold plays {self._san(afrm)}{self._san(ato)}.{detail_ai} Checkmate! Harold wins."
                return self.render() + f"\nHarold plays {self._san(afrm)}{self._san(ato)}.{detail_ai} Stalemate. Draw."
            if self._in_check("w"):
                detail_ai = " Check!" + detail_ai
            self.turn = "w"
            return self.render() + f"\nHarold plays {self._san(afrm)}{self._san(ato)}.{detail_ai}"
        return self.render() + f"\nYou moved {text}.{detail}"

    def render(self) -> str:
        rows = []
        for r in range(8):
            cells = []
            for c in range(8):
                p = self.board[self._sq(r, c)]
                cells.append(p or ".")
            rows.append(f"{8 - r} " + " ".join(cells))
        rows.append("   a b c d e f g h")
        return "\n".join(rows)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


GAMES: dict[str, type[Game]] = {
    "tictactoe": TicTacToe,
    "ttt": TicTacToe,
    "hangman": Hangman,
    "checkers": Checkers,
    "chess": Chess,
}


def list_games() -> str:
    return ", ".join(sorted({k for k in GAMES if len(k) > 3}))


def create(name: str) -> Optional[Game]:
    cls = GAMES.get(name.strip().lower())
    if cls is None:
        return None
    return cls()
