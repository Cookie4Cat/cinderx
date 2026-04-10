#!/usr/bin/env python3
"""
性能诊断脚本 - CPython vs CinderX JIT 性能对比
"""

import sys
import time
import statistics
from pathlib import Path

# 添加 PythonLib 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "cinderx" / "PythonLib"))

class Node:
    """使用递归生成器迭代器的树节点。"""

    def __init__(self, value, left=None, right=None):
        self.value = value
        self.left = left
        self.right = right

    def __iter__(self):
        if self.left:
            yield from self.left
        yield self.value
        if self.right:
            yield from self.right


class StackNode:
    """使用栈式（非递归）迭代器的树节点。"""

    def __init__(self, value, left=None, right=None):
        self.value = value
        self.left = left
        self.right = right

    def __iter__(self):
        stack = [(self, False, False)]
        while stack:
            node, left_done, right_done = stack.pop()
            if not left_done and node.left:
                stack.append((node, True, False))
                stack.append((node.left, False, False))
            elif not right_done:
                yield node.value
                if node.right:
                    stack.append((node, True, True))
                    stack.append((node.right, False, False))


def build_tree(node_cls, depth):
    """构建平衡二叉树。"""
    if depth == 0:
        return None
    mid = 2 ** (depth - 1)
    return node_cls(
        mid, build_tree(node_cls, depth - 1), build_tree(node_cls, depth - 1)
    )


def traverse(tree):
    """遍历树并返回总和。"""
    s = 0
    for v in tree:
        s += v
    return s


def bench(tree, iterations=10):
    """基准测试树遍历。"""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        traverse(tree)
        times.append(time.perf_counter() - start)
    return statistics.mean(times), statistics.stdev(times)


def main():
    print("=" * 60)
    print("CinderX JIT 性能诊断")
    print("=" * 60)

    depth = 15
    iterations = 15

    # 测试 1：CPython 解释器基线
    print("\n[1] CPython 解释器（递归生成器）")
    tree1 = build_tree(Node, depth)
    mean1, std1 = bench(tree1, iterations)
    print(f"    时间: {mean1*1000:.3f}ms ± {std1*1000:.3f}ms")

    # 测试 2：CPython 解释器（栈式迭代器）
    print("\n[2] CPython 解释器（栈式迭代器）")
    tree2 = build_tree(StackNode, depth)
    mean2, std2 = bench(tree2, iterations)
    print(f"    时间: {mean2*1000:.3f}ms ± {std2*1000:.3f}ms")
    print(f"    加速比: {mean1/mean2:.2f}x")

    # 测试 3：CinderX JIT（如果可用）
    try:
        import cinderjit

        print("\n[3] CinderX JIT（递归生成器）")

        # 启用 JIT
        cinderjit.enable()

        # 强制编译 Node.__iter__
        cinderjit.force_compile(Node.__iter__)

        # 构建新树（使用 JIT）
        tree3 = build_tree(Node, depth)

        # 预热
        for _ in range(5):
            traverse(tree3)

        # 测量
        mean3, std3 = bench(tree3, iterations)
        print(f"    时间: {mean3*1000:.3f}ms ± {std3*1000:.3f}ms")
        print(f"    vs CPython: {mean1/mean3:.2f}x")
        print(f"    vs 栈式: {mean2/mean3:.2f}x")

        # 编译信息
        print(f"\n    Node.__iter__ 已编译: {cinderjit.is_jit_compiled(Node.__iter__)}")
        if cinderjit.is_jit_compiled(Node.__iter__):
            print(f"    代码大小: {cinderjit.get_compiled_size(Node.__iter__)} bytes")

    except ImportError:
        print("\n[3] CinderX 不可用")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
