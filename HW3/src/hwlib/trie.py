"""
trie.py — Radix Trie（壓縮字典樹），用於儲存詞彙並支援前綴查詢。

與一般 trie 的差異：只有單一子節點的路徑會被合併成一條邊，邊上存整段字串
（label），而不是每個字元一個節點。例如 "test"、"team" 共用 "te" 這條邊，
之後分岔為 "st" 與 "am"。節點數因此大約與詞彙數同階，而非與總字元數同階。

用途：
  - get(term)：精確查詢（Python dict 更快，trie 的價值在下一項）
  - prefix_search(prefix)：依字典序列出所有以 prefix 開頭的詞，
    例如 prefix_search("comput") → compute, computer, computing, ...
"""
from __future__ import annotations

_EMPTY = object()   # 哨兵：表示此節點不是任何詞的結尾（不能用 None，值本身可能是 None）


class _Node:
    __slots__ = ("label", "children", "value")

    def __init__(self, label: str, value=_EMPTY):
        self.label = label            # 從父節點到此節點的邊上字串
        self.children = None          # dict[首字元, _Node]；葉節點保持 None 以節省記憶體
        self.value = value            # 若此節點是某個詞的結尾，存該詞的值


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


class RadixTrie:
    def __init__(self):
        self.root = _Node("")
        self._size = 0

    def __len__(self):
        return self._size

    def __contains__(self, key):
        node = self._find(key)
        return node is not None and node.value is not _EMPTY

    # ---- 插入 --------------------------------------------------------------
    def insert(self, key: str, value) -> None:
        node, rest = self.root, key
        while True:
            if not rest:
                # 走到底：key 結束在這個節點
                if node.value is _EMPTY:
                    self._size += 1
                node.value = value
                return

            if node.children is None:
                node.children = {}
            child = node.children.get(rest[0])

            if child is None:
                # 沒有共用首字元的子節點：直接掛一個新葉節點，邊上放剩餘整段字串
                node.children[rest[0]] = _Node(rest, value)
                self._size += 1
                return

            label = child.label
            i = _common_prefix_len(label, rest)
            if i == len(label):
                # 子節點的整段 label 都吻合：往下走
                node, rest = child, rest[i:]
                continue

            # 只吻合 label 的前 i 個字元：在第 i 個字元處切開這條邊
            #   node --label--> child   變成   node --label[:i]--> mid --label[i:]--> child
            mid = _Node(label[:i])
            mid.children = {label[i]: child}
            child.label = label[i:]
            node.children[rest[0]] = mid

            if i == len(rest):
                mid.value = value                      # key 剛好結束在切點
            else:
                mid.children[rest[i]] = _Node(rest[i:], value)  # 另開一條分支
            self._size += 1
            return

    # ---- 精確查詢 ------------------------------------------------------------
    def _find(self, key: str):
        node, rest = self.root, key
        while rest:
            if node.children is None:
                return None
            child = node.children.get(rest[0])
            if child is None or not rest.startswith(child.label):
                return None
            node, rest = child, rest[len(child.label):]
        return node

    def get(self, key: str, default=None):
        node = self._find(key)
        if node is None or node.value is _EMPTY:
            return default
        return node.value

    # ---- 前綴查詢 ------------------------------------------------------------
    def prefix_search(self, prefix: str, limit: int | None = None) -> list[tuple[str, object]]:
        """回傳所有以 prefix 開頭的 (term, value)，依字典序排列；limit 可限制筆數。"""
        node, rest, acc = self.root, prefix, ""

        # 1. 沿著 prefix 往下走；prefix 可能在某條邊的中間結束
        while rest:
            if node.children is None:
                return []
            child = node.children.get(rest[0])
            if child is None:
                return []
            label = child.label
            if rest.startswith(label):          # 整條邊都在 prefix 內
                acc, rest, node = acc + label, rest[len(label):], child
            elif label.startswith(rest):        # prefix 在這條邊中間結束
                acc, rest, node = acc + label, "", child
            else:
                return []

        # 2. 從該節點做前序 DFS。節點本身的詞是其子孫的前綴，必定排在前面；
        #    兄弟節點的首字元互不相同，依首字元排序即為字典序。
        out = []
        stack = [(node, acc)]
        while stack:
            n, s = stack.pop()
            if n.value is not _EMPTY:
                out.append((s, n.value))
                if limit and len(out) >= limit:
                    break
            if n.children:
                for ch in sorted(n.children, reverse=True):  # 反向推入，小的先彈出
                    c = n.children[ch]
                    stack.append((c, s + c.label))
        return out

    # ---- 統計 ---------------------------------------------------------------
    def node_count(self) -> int:
        count, stack = 0, [self.root]
        while stack:
            n = stack.pop()
            count += 1
            if n.children:
                stack.extend(n.children.values())
        return count