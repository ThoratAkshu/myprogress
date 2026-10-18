"""The problem set: coding problems like LeetCode's, solved in Python or JavaScript in the browser.

Each problem has a statement, examples (its first tests), constraints, hints, an editorial, and a reference solution
in both languages. The tests call the function with JSON arguments and compare what it returns. The test suite runs
every Python solution against every test; the JavaScript ones are run in a browser. Two independent solutions agreeing
with each expected answer is the check on the answers themselves."""
import re

DIFFICULTIES = [("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")]


def snake_to_camel(name):
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def problem(number, slug, title, difficulty, topics, fn, params, statement, constraints, hints, editorial, complexity, python, javascript, tests,
            examples=2, compare="exact"):
    """tests: (args, expected) or (args, expected, explanation). compare: exact, sorted (any order), nested (groups in
    any order, items in any order), or float (within 1e-5)."""
    cases = [{"args": list(test[0]), "expected": test[1], "why": test[2] if len(test) > 2 else ""} for test in tests]
    js_fn = snake_to_camel(fn)
    return {
        "number": number, "slug": slug, "title": title, "difficulty": difficulty, "topics": topics, "params": params,
        "statement": statement.strip(), "constraints": constraints, "hints": hints, "editorial": editorial.strip(), "complexity": complexity,
        "compare": compare, "tests": cases, "examples": examples,
        "languages": {
            "python": {"fn": fn, "starter": f"def {fn}({', '.join(params)}):\n    pass\n", "solution": python.strip("\n") + "\n"},
            "javascript": {"fn": js_fn, "starter": f"function {js_fn}({', '.join(params)}) {{\n  \n}}\n", "solution": javascript.strip("\n") + "\n"},
        },
    }


PROBLEMS = [
    problem(1, "two-sum", "Two Sum", "easy", ["Array", "Hash Table"], "two_sum", ["nums", "target"], """
Given a list of integers `nums` and an integer `target`, return the positions of the two numbers that add up to `target`, as `[i, j]` with `i < j`.

There is always exactly one answer, and you can't use the same element twice.""",
            ["2 ≤ nums.length ≤ 10⁴", "-10⁹ ≤ nums[i], target ≤ 10⁹", "Exactly one answer exists"],
            ["Checking every pair works but takes O(n²). Can you remember what you've seen?", "For each number, the partner you need is `target - number`. A hash map finds it in O(1)."],
            """Walk through the list once, keeping a map from each number seen to its position. For each number, check whether `target - number` is already in the map: if it is, those two positions are the answer. Otherwise remember this number and move on.""",
            "Time O(n), space O(n)", """
def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
    return []
""", """
function twoSum(nums, target) {
  const seen = new Map();
  for (let i = 0; i < nums.length; i++) {
    const need = target - nums[i];
    if (seen.has(need)) return [seen.get(need), i];
    seen.set(nums[i], i);
  }
  return [];
}
""", [(([2, 7, 11, 15], 9), [0, 1], "nums[0] + nums[1] = 2 + 7 = 9"), (([3, 2, 4], 6), [1, 2]), (([3, 3], 6), [0, 1]), (([1, 5, 1], 2), [0, 2]),
      (([-1, -2, -3, -4, -5], -8), [2, 4]), (([0, 4, 3, 0], 0), [0, 3])], examples=3),

    problem(2, "valid-parentheses", "Valid Parentheses", "easy", ["String", "Stack"], "is_valid", ["s"], """
Given a string `s` of the characters `(`, `)`, `[`, `]`, `{` and `}`, return `true` if every bracket is closed by the same kind, in the right order.

An empty string is valid.""",
            ["0 ≤ s.length ≤ 10⁴", "s has only brackets"],
            ["The most recent open bracket must be closed first.", "Push open brackets on a stack; a closing bracket must match the top."],
            """Use a stack. Push every opening bracket. For a closing bracket, the stack's top must be its partner: pop it, or return false if it doesn't match or the stack is empty. At the end the stack must be empty, or some bracket was never closed.""",
            "Time O(n), space O(n)", """
def is_valid(s):
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for ch in s:
        if ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
        else:
            stack.append(ch)
    return not stack
""", """
function isValid(s) {
  const pairs = { ")": "(", "]": "[", "}": "{" };
  const stack = [];
  for (const ch of s) {
    if (ch in pairs) {
      if (stack.pop() !== pairs[ch]) return false;
    } else {
      stack.push(ch);
    }
  }
  return stack.length === 0;
}
""", [(("()",), True), (("()[]{}",), True), (("(]",), False, "( is closed by ], which isn't its partner"), (("([)]",), False), (("{[]}",), True),
      (("",), True), (("((",), False), (("]",), False)], examples=3),

    problem(3, "valid-palindrome", "Valid Palindrome", "easy", ["String", "Two Pointers"], "is_palindrome", ["s"], """
A phrase is a palindrome if, after making every letter lower case and removing everything that isn't a letter or a digit, it reads the same forwards and backwards.

Given a string `s`, return `true` if it's a palindrome.""",
            ["1 ≤ s.length ≤ 2·10⁵", "s has printable ASCII characters"],
            ["Clean the string first, or skip unwanted characters as you go.", "Compare from both ends towards the middle."],
            """Keep only letters and digits, in lower case, then compare the cleaned string with its reverse. To save memory, use two pointers instead: move them towards each other, skipping anything that isn't a letter or digit, and compare as you go.""",
            "Time O(n), space O(n) (O(1) with two pointers)", """
def is_palindrome(s):
    cleaned = [ch.lower() for ch in s if ch.isalnum()]
    return cleaned == cleaned[::-1]
""", """
function isPalindrome(s) {
  const cleaned = s.toLowerCase().replace(/[^a-z0-9]/g, "");
  return cleaned === [...cleaned].reverse().join("");
}
""", [(("A man, a plan, a canal: Panama",), True, '"amanaplanacanalpanama" reads the same both ways'), (("race a car",), False), ((" ",), True),
      (("0P",), False), (("ab_a",), True)]),

    problem(4, "best-time-to-buy-and-sell-stock", "Best Time to Buy and Sell Stock", "easy", ["Array", "Greedy"], "max_profit", ["prices"], """
`prices[i]` is a share's price on day `i`. Buy on one day and sell on a later day: return the most profit you can make, or `0` if no trade makes money.""",
            ["1 ≤ prices.length ≤ 10⁵", "0 ≤ prices[i] ≤ 10⁴"],
            ["For each day, the best sale is today's price minus the lowest price before it."],
            """Track the lowest price so far. Each day, the best profit selling today is the price minus that lowest price; keep the best of those. One pass, no nested loops.""",
            "Time O(n), space O(1)", """
def max_profit(prices):
    lowest, best = float("inf"), 0
    for price in prices:
        lowest = min(lowest, price)
        best = max(best, price - lowest)
    return best
""", """
function maxProfit(prices) {
  let lowest = Infinity;
  let best = 0;
  for (const price of prices) {
    lowest = Math.min(lowest, price);
    best = Math.max(best, price - lowest);
  }
  return best;
}
""", [(([7, 1, 5, 3, 6, 4],), 5, "Buy at 1 on day 1 and sell at 6 on day 4"), (([7, 6, 4, 3, 1],), 0, "Prices only fall, so don't trade"), (([2, 4, 1],), 2),
      (([1],), 0), (([3, 3, 5, 0, 0, 3, 1, 4],), 4)]),

    problem(5, "contains-duplicate", "Contains Duplicate", "easy", ["Array", "Hash Table"], "contains_duplicate", ["nums"], """
Given a list of integers `nums`, return `true` if any value appears at least twice, and `false` if every value is different.""",
            ["0 ≤ nums.length ≤ 10⁵", "-10⁹ ≤ nums[i] ≤ 10⁹"],
            ["A set keeps one of each value."],
            """Put the numbers in a set: if the set is smaller than the list, something repeated. Or stop early: add numbers one by one and return true as soon as one is already in the set.""",
            "Time O(n), space O(n)", """
def contains_duplicate(nums):
    return len(set(nums)) < len(nums)
""", """
function containsDuplicate(nums) {
  return new Set(nums).size < nums.length;
}
""", [(([1, 2, 3, 1],), True), (([1, 2, 3, 4],), False), (([1, 1, 1, 3, 3, 4, 3, 2, 4, 2],), True), (([],), False)]),

    problem(6, "valid-anagram", "Valid Anagram", "easy", ["String", "Hash Table", "Sorting"], "is_anagram", ["s", "t"], """
Given two strings `s` and `t`, return `true` if `t` uses exactly the same letters as `s`, each the same number of times.""",
            ["0 ≤ s.length, t.length ≤ 5·10⁴", "s and t have lower-case English letters"],
            ["Different lengths can't be anagrams.", "Count each letter in one string, then use the counts up with the other."],
            """Count how often each letter appears in `s`. Then go through `t`, taking one off each letter's count; if a count would go below zero, it isn't an anagram. Sorting both strings and comparing also works, in O(n log n).""",
            "Time O(n), space O(1) (26 letters)", """
def is_anagram(s, t):
    if len(s) != len(t):
        return False
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    for ch in t:
        if counts.get(ch, 0) == 0:
            return False
        counts[ch] -= 1
    return True
""", """
function isAnagram(s, t) {
  if (s.length !== t.length) return false;
  const counts = new Map();
  for (const ch of s) counts.set(ch, (counts.get(ch) || 0) + 1);
  for (const ch of t) {
    if (!counts.get(ch)) return false;
    counts.set(ch, counts.get(ch) - 1);
  }
  return true;
}
""", [(("anagram", "nagaram"), True), (("rat", "car"), False), (("a", "ab"), False), (("", ""), True)]),

    problem(7, "merge-sorted-lists", "Merge Two Sorted Lists", "easy", ["Array", "Two Pointers"], "merge_sorted", ["a", "b"], """
Given two lists `a` and `b`, each sorted from smallest to largest, return one sorted list with all their values.""",
            ["0 ≤ a.length, b.length ≤ 50", "-100 ≤ values ≤ 100"],
            ["The smallest value left is always at the front of one of the lists."],
            """Keep a pointer into each list. Repeatedly take the smaller of the two front values and move that pointer on. When one list runs out, add what's left of the other.""",
            "Time O(m + n), space O(m + n)", """
def merge_sorted(a, b):
    merged, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            merged.append(a[i])
            i += 1
        else:
            merged.append(b[j])
            j += 1
    return merged + a[i:] + b[j:]
""", """
function mergeSorted(a, b) {
  const merged = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] <= b[j]) merged.push(a[i++]);
    else merged.push(b[j++]);
  }
  return merged.concat(a.slice(i), b.slice(j));
}
""", [(([1, 2, 4], [1, 3, 4]), [1, 1, 2, 3, 4, 4]), (([], [0]), [0]), (([], []), []), (([5], [1, 2, 3]), [1, 2, 3, 5])]),

    problem(8, "missing-number", "Missing Number", "easy", ["Array", "Math"], "missing_number", ["nums"], """
`nums` holds `n` different numbers from the range `0` to `n`, so exactly one number in that range is missing. Return it.""",
            ["1 ≤ n ≤ 10⁴", "All numbers in nums are different"],
            ["What should the numbers from 0 to n add up to?"],
            """The numbers 0 to n add up to n(n + 1)/2. Subtract the actual sum of `nums`, and what's left is the missing number. XOR-ing every index and value works too, without any risk of big sums.""",
            "Time O(n), space O(1)", """
def missing_number(nums):
    n = len(nums)
    return n * (n + 1) // 2 - sum(nums)
""", """
function missingNumber(nums) {
  const n = nums.length;
  return n * (n + 1) / 2 - nums.reduce((a, b) => a + b, 0);
}
""", [(([3, 0, 1],), 2, "n = 3, so the range is 0 to 3, and 2 isn't there"), (([0, 1],), 2), (([9, 6, 4, 2, 3, 5, 7, 0, 1],), 8), (([0],), 1), (([1],), 0)]),

    problem(9, "binary-search", "Binary Search", "easy", ["Array", "Binary Search"], "search", ["nums", "target"], """
Given a list of integers `nums` sorted from smallest to largest, return the position of `target`, or `-1` if it isn't there.

Your solution should take O(log n) time.""",
            ["0 ≤ nums.length ≤ 10⁴", "All values are different", "nums is sorted"],
            ["Look at the middle value: which half can the target be in?"],
            """Keep a range `low` to `high`. Look at the middle: if it's the target, done; if it's smaller, the target can only be to the right, so move `low` past it; otherwise move `high` before it. Each step halves the range.""",
            "Time O(log n), space O(1)", """
def search(nums, target):
    low, high = 0, len(nums) - 1
    while low <= high:
        mid = (low + high) // 2
        if nums[mid] == target:
            return mid
        if nums[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
""", """
function search(nums, target) {
  let low = 0;
  let high = nums.length - 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    if (nums[mid] === target) return mid;
    if (nums[mid] < target) low = mid + 1;
    else high = mid - 1;
  }
  return -1;
}
""", [(([-1, 0, 3, 5, 9, 12], 9), 4, "9 is at position 4"), (([-1, 0, 3, 5, 9, 12], 2), -1), (([5], 5), 0), (([], 1), -1), (([1, 3], 3), 1)]),

    problem(10, "climbing-stairs", "Climbing Stairs", "easy", ["Dynamic Programming", "Math"], "climb_stairs", ["n"], """
A staircase has `n` steps, and you climb 1 or 2 steps at a time. In how many different ways can you reach the top?""",
            ["1 ≤ n ≤ 45"],
            ["The last move to step n came from step n − 1 or step n − 2.", "So ways(n) = ways(n − 1) + ways(n − 2): the Fibonacci numbers."],
            """Every way to reach step n ends with a 1-step from n − 1 or a 2-step from n − 2, so ways(n) = ways(n − 1) + ways(n − 2). Keep just the last two values while counting up from 1.""",
            "Time O(n), space O(1)", """
def climb_stairs(n):
    one, two = 1, 1
    for _ in range(n - 1):
        one, two = one + two, one
    return one
""", """
function climbStairs(n) {
  let one = 1;
  let two = 1;
  for (let i = 1; i < n; i++) {
    [one, two] = [one + two, one];
  }
  return one;
}
""", [((2,), 2, "1 + 1, or 2"), ((3,), 3, "1 + 1 + 1, 1 + 2, or 2 + 1"), ((1,), 1), ((5,), 8), ((10,), 89), ((45,), 1836311903)]),

    problem(11, "majority-element", "Majority Element", "easy", ["Array", "Hash Table", "Counting"], "majority_element", ["nums"], """
Given a list `nums` of length `n`, return the value that appears more than `n / 2` times. There always is one.""",
            ["1 ≤ n ≤ 5·10⁴", "A majority value always exists"],
            ["Counting with a hash map works. Can you do it in O(1) space?", "Pair each majority value off against a different one: what's left?"],
            """The Boyer–Moore vote: keep a candidate and a count. When the count is zero, take the current value as the candidate; then add one for a match and subtract one otherwise. The majority value outnumbers everything else, so it's the candidate at the end.""",
            "Time O(n), space O(1)", """
def majority_element(nums):
    candidate, count = None, 0
    for n in nums:
        if count == 0:
            candidate = n
        count += 1 if n == candidate else -1
    return candidate
""", """
function majorityElement(nums) {
  let candidate = null;
  let count = 0;
  for (const n of nums) {
    if (count === 0) candidate = n;
    count += n === candidate ? 1 : -1;
  }
  return candidate;
}
""", [(([3, 2, 3],), 3), (([2, 2, 1, 1, 1, 2, 2],), 2), (([1],), 1), (([6, 5, 5],), 5)]),

    problem(12, "sum-of-even-numbers", "Sum of Even Numbers", "easy", ["Array"], "sum_evens", ["nums"], """
Return the sum of the even numbers in `nums`. An empty list adds up to `0`.""",
            ["0 ≤ nums.length ≤ 10⁴", "-10⁴ ≤ nums[i] ≤ 10⁴"],
            ["A number is even when dividing by 2 leaves no remainder."],
            """Go through the list and add each number whose remainder after dividing by 2 is zero. Negative even numbers count too.""",
            "Time O(n), space O(1)", """
def sum_evens(nums):
    total = 0
    for n in nums:
        if n % 2 == 0:
            total += n
    return total
""", """
function sumEvens(nums) {
  let total = 0;
  for (const n of nums) {
    if (n % 2 === 0) total += n;
  }
  return total;
}
""", [(([1, 2, 3, 4],), 6, "2 + 4"), (([],), 0), (([7, 9],), 0), (([-2, 3, 10],), 8)]),

    problem(13, "fizz-buzz", "Fizz Buzz", "easy", ["Math", "String"], "fizz_buzz", ["n"], """
Return a list of the numbers 1 to `n` as strings, except: multiples of 3 become `"Fizz"`, multiples of 5 become `"Buzz"`, and multiples of both become `"FizzBuzz"`.""",
            ["1 ≤ n ≤ 10⁴"],
            ["Check multiples of 15 first."],
            """For each number, check divisibility by 15 first (both 3 and 5), then 3, then 5; otherwise use the number itself as a string.""",
            "Time O(n), space O(n)", """
def fizz_buzz(n):
    out = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            out.append("FizzBuzz")
        elif i % 3 == 0:
            out.append("Fizz")
        elif i % 5 == 0:
            out.append("Buzz")
        else:
            out.append(str(i))
    return out
""", """
function fizzBuzz(n) {
  const out = [];
  for (let i = 1; i <= n; i++) {
    if (i % 15 === 0) out.push("FizzBuzz");
    else if (i % 3 === 0) out.push("Fizz");
    else if (i % 5 === 0) out.push("Buzz");
    else out.push(String(i));
  }
  return out;
}
""", [((3,), ["1", "2", "Fizz"]), ((5,), ["1", "2", "Fizz", "4", "Buzz"]), ((1,), ["1"]),
      ((15,), ["1", "2", "Fizz", "4", "Buzz", "Fizz", "7", "8", "Fizz", "Buzz", "11", "Fizz", "13", "14", "FizzBuzz"])]),

    problem(14, "longest-substring-without-repeating-characters", "Longest Substring Without Repeating Characters", "medium", ["String", "Sliding Window", "Hash Table"],
            "length_of_longest_substring", ["s"], """
Given a string `s`, return the length of the longest substring (a run of neighbouring characters) in which no character repeats.""",
            ["0 ≤ s.length ≤ 5·10⁴", "s has letters, digits, symbols and spaces"],
            ["Grow a window to the right; when a character repeats, move the window's start past its last appearance."],
            """Slide a window over the string. Remember where each character was last seen. When the new character was seen inside the window, move the window's start to just after that place. The longest window seen is the answer.""",
            "Time O(n), space O(alphabet)", """
def length_of_longest_substring(s):
    last, start, best = {}, 0, 0
    for i, ch in enumerate(s):
        if ch in last and last[ch] >= start:
            start = last[ch] + 1
        last[ch] = i
        best = max(best, i - start + 1)
    return best
""", """
function lengthOfLongestSubstring(s) {
  const last = new Map();
  let start = 0;
  let best = 0;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (last.has(ch) && last.get(ch) >= start) start = last.get(ch) + 1;
    last.set(ch, i);
    best = Math.max(best, i - start + 1);
  }
  return best;
}
""", [(("abcabcbb",), 3, '"abc" is the longest without a repeat'), (("bbbbb",), 1), (("pwwkew",), 3, '"wke"; "pwke" isn\'t a substring'), (("",), 0), ((" ",), 1),
      (("dvdf",), 3), (("abba",), 2)], examples=3),

    problem(15, "group-anagrams", "Group Anagrams", "medium", ["String", "Hash Table", "Sorting"], "group_anagrams", ["strs"], """
Given a list of words `strs`, group the anagrams together: words made of exactly the same letters. Return the groups in any order, with the words in each group in any order.""",
            ["1 ≤ strs.length ≤ 10⁴", "0 ≤ strs[i].length ≤ 100", "Lower-case English letters"],
            ["Two words are anagrams when their letters, sorted, are the same."],
            """Give each word a key that's the same for all its anagrams: its letters sorted. Collect words in a hash map from key to list, and return the lists. Counting the 26 letters instead of sorting makes each key O(length).""",
            "Time O(n · k log k) for n words of length k, space O(n · k)", """
def group_anagrams(strs):
    groups = {}
    for word in strs:
        groups.setdefault("".join(sorted(word)), []).append(word)
    return list(groups.values())
""", """
function groupAnagrams(strs) {
  const groups = new Map();
  for (const word of strs) {
    const key = [...word].sort().join("");
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(word);
  }
  return [...groups.values()];
}
""", [((["eat", "tea", "tan", "ate", "nat", "bat"],), [["bat"], ["nat", "tan"], ["ate", "eat", "tea"]]), (([""],), [[""]]), ((["a"],), [["a"]]),
      ((["abc", "bca", "cab", "xyz", "zyx", "q"],), [["abc", "bca", "cab"], ["xyz", "zyx"], ["q"]])], compare="nested"),

    problem(16, "product-of-array-except-self", "Product of Array Except Self", "medium", ["Array", "Prefix Sum"], "product_except_self", ["nums"], """
Return a list `answer` where `answer[i]` is the product of every number in `nums` except `nums[i]`. Don't use division, and take O(n) time.""",
            ["2 ≤ nums.length ≤ 10⁵", "-30 ≤ nums[i] ≤ 30", "Every product fits in a 32-bit integer"],
            ["answer[i] = (product of everything left of i) × (product of everything right of i)."],
            """Make one pass from the left, storing at each position the product of everything before it. Then pass from the right with a running product of everything after it, multiplying it in. No division, so zeros are fine.""",
            "Time O(n), space O(1) besides the answer", """
def product_except_self(nums):
    answer = [1] * len(nums)
    left = 1
    for i in range(len(nums)):
        answer[i] = left
        left *= nums[i]
    right = 1
    for i in range(len(nums) - 1, -1, -1):
        answer[i] *= right
        right *= nums[i]
    return answer
""", """
function productExceptSelf(nums) {
  const answer = new Array(nums.length).fill(1);
  let left = 1;
  for (let i = 0; i < nums.length; i++) {
    answer[i] = left;
    left *= nums[i];
  }
  let right = 1;
  for (let i = nums.length - 1; i >= 0; i--) {
    answer[i] *= right;
    right *= nums[i];
  }
  return answer;
}
""", [(([1, 2, 3, 4],), [24, 12, 8, 6]), (([-1, 1, 0, -3, 3],), [0, 0, 9, 0, 0]), (([2, 3],), [3, 2]), (([0, 0],), [0, 0]), (([1, 0],), [0, 1]),
      (([2, -1, 4],), [-4, 8, -2])]),

    problem(17, "top-k-frequent-elements", "Top K Frequent Elements", "medium", ["Array", "Hash Table", "Sorting"], "top_k_frequent", ["nums", "k"], """
Return the `k` values that appear most often in `nums`, in any order. The answer is always unique.""",
            ["1 ≤ nums.length ≤ 10⁵", "1 ≤ k ≤ number of different values"],
            ["Count each value first.", "Sorting the counts is O(n log n); buckets by count make it O(n)."],
            """Count each value with a hash map, then take the k values with the highest counts: sort by count, or use a heap of size k, or put values into buckets indexed by count and read the buckets from the top.""",
            "Time O(n log n) with sorting (O(n) with buckets), space O(n)", """
def top_k_frequent(nums, k):
    counts = {}
    for n in nums:
        counts[n] = counts.get(n, 0) + 1
    return sorted(counts, key=counts.get, reverse=True)[:k]
""", """
function topKFrequent(nums, k) {
  const counts = new Map();
  for (const n of nums) counts.set(n, (counts.get(n) || 0) + 1);
  return [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a)).slice(0, k);
}
""", [(([1, 1, 1, 2, 2, 3], 2), [1, 2]), (([1], 1), [1]), (([4, 4, 4, 5, 5, 6, 6, 6, 6], 2), [4, 6]), (([5, 5, 7, 7, 7, 9], 1), [7]),
      (([-1, -1, 2], 2), [-1, 2]), (([3, 0, 1, 0], 1), [0])], compare="sorted"),

    problem(18, "maximum-subarray", "Maximum Subarray", "medium", ["Array", "Dynamic Programming"], "max_sub_array", ["nums"], """
Find the run of one or more neighbouring numbers in `nums` with the largest sum, and return that sum.""",
            ["1 ≤ nums.length ≤ 10⁵", "-10⁴ ≤ nums[i] ≤ 10⁴"],
            ["The best run ending here either continues the best run ending just before, or starts fresh."],
            """Kadane's algorithm: keep the best sum of a run ending at the current number. It's either the number alone or the number plus the best run ending just before it, whichever is bigger. The largest of those is the answer.""",
            "Time O(n), space O(1)", """
def max_sub_array(nums):
    best = current = nums[0]
    for n in nums[1:]:
        current = max(n, current + n)
        best = max(best, current)
    return best
""", """
function maxSubArray(nums) {
  let best = nums[0];
  let current = nums[0];
  for (let i = 1; i < nums.length; i++) {
    current = Math.max(nums[i], current + nums[i]);
    best = Math.max(best, current);
  }
  return best;
}
""", [(([-2, 1, -3, 4, -1, 2, 1, -5, 4],), 6, "[4, -1, 2, 1] adds up to 6"), (([1],), 1), (([5, 4, -1, 7, 8],), 23), (([-3, -1, -2],), -1)]),

    problem(19, "three-sum", "3Sum", "medium", ["Array", "Two Pointers", "Sorting"], "three_sum", ["nums"], """
Return every different triplet `[a, b, c]` of values from `nums` (at three different positions) that adds up to `0`. No triplet may appear twice. Return them in any order.""",
            ["3 ≤ nums.length ≤ 3000", "-10⁵ ≤ nums[i] ≤ 10⁵"],
            ["Sort first. Fix the first value, then find pairs for the rest with two pointers.", "Skip equal neighbours to avoid repeats."],
            """Sort the list. For each first value (skipping repeats), look for two more in the rest with pointers at both ends: if the sum is too small move the left one right, too big move the right one left, and on zero record it and skip past equal values.""",
            "Time O(n²), space O(1) besides the output", """
def three_sum(nums):
    nums = sorted(nums)
    found = []
    for i in range(len(nums) - 2):
        if i > 0 and nums[i] == nums[i - 1]:
            continue
        low, high = i + 1, len(nums) - 1
        while low < high:
            total = nums[i] + nums[low] + nums[high]
            if total < 0:
                low += 1
            elif total > 0:
                high -= 1
            else:
                found.append([nums[i], nums[low], nums[high]])
                while low < high and nums[low] == nums[low + 1]:
                    low += 1
                while low < high and nums[high] == nums[high - 1]:
                    high -= 1
                low += 1
                high -= 1
    return found
""", """
function threeSum(nums) {
  const sorted = [...nums].sort((a, b) => a - b);
  const found = [];
  for (let i = 0; i < sorted.length - 2; i++) {
    if (i > 0 && sorted[i] === sorted[i - 1]) continue;
    let low = i + 1;
    let high = sorted.length - 1;
    while (low < high) {
      const total = sorted[i] + sorted[low] + sorted[high];
      if (total < 0) low++;
      else if (total > 0) high--;
      else {
        found.push([sorted[i], sorted[low], sorted[high]]);
        while (low < high && sorted[low] === sorted[low + 1]) low++;
        while (low < high && sorted[high] === sorted[high - 1]) high--;
        low++;
        high--;
      }
    }
  }
  return found;
}
""", [(([-1, 0, 1, 2, -1, -4],), [[-1, -1, 2], [-1, 0, 1]]), (([0, 1, 1],), []), (([0, 0, 0],), [[0, 0, 0]]), (([-2, 0, 1, 1, 2],), [[-2, 0, 2], [-2, 1, 1]])],
            compare="nested"),

    problem(20, "container-with-most-water", "Container With Most Water", "medium", ["Array", "Two Pointers", "Greedy"], "max_area", ["height"], """
`height[i]` is the height of a vertical line at position `i`. Two lines and the floor make a container: its water is the distance between the lines times the shorter line. Return the most water any container can hold.""",
            ["2 ≤ height.length ≤ 10⁵", "0 ≤ height[i] ≤ 10⁴"],
            ["Start with the widest container. Which side can't be part of anything better?"],
            """Start with pointers at both ends. The shorter line limits the water, and moving the taller one inwards can only make things worse, so always move the shorter one. Record the best area as you go.""",
            "Time O(n), space O(1)", """
def max_area(height):
    low, high, best = 0, len(height) - 1, 0
    while low < high:
        best = max(best, (high - low) * min(height[low], height[high]))
        if height[low] < height[high]:
            low += 1
        else:
            high -= 1
    return best
""", """
function maxArea(height) {
  let low = 0;
  let high = height.length - 1;
  let best = 0;
  while (low < high) {
    best = Math.max(best, (high - low) * Math.min(height[low], height[high]));
    if (height[low] < height[high]) low++;
    else high--;
  }
  return best;
}
""", [(([1, 8, 6, 2, 5, 4, 8, 3, 7],), 49, "The lines at positions 1 and 8: 7 apart, 7 high"), (([1, 1],), 1), (([4, 3, 2, 1, 4],), 16), (([1, 2, 1],), 2)]),

    problem(21, "search-in-rotated-sorted-array", "Search in Rotated Sorted Array", "medium", ["Array", "Binary Search"], "search_rotated", ["nums", "target"], """
A sorted list of different integers was rotated: some prefix moved to the end, like `[0, 1, 2, 4, 5, 6, 7]` becoming `[4, 5, 6, 7, 0, 1, 2]`. Return the position of `target`, or `-1`. Take O(log n) time.""",
            ["1 ≤ nums.length ≤ 5000", "All values are different"],
            ["Around any middle point, one half is still sorted. Is the target inside that half?"],
            """Binary search with one extra question: which half is sorted? If the left half is sorted and the target lies within its range, search left, otherwise right. If the right half is sorted, do the same mirrored.""",
            "Time O(log n), space O(1)", """
def search_rotated(nums, target):
    low, high = 0, len(nums) - 1
    while low <= high:
        mid = (low + high) // 2
        if nums[mid] == target:
            return mid
        if nums[low] <= nums[mid]:
            if nums[low] <= target < nums[mid]:
                high = mid - 1
            else:
                low = mid + 1
        else:
            if nums[mid] < target <= nums[high]:
                low = mid + 1
            else:
                high = mid - 1
    return -1
""", """
function searchRotated(nums, target) {
  let low = 0;
  let high = nums.length - 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    if (nums[mid] === target) return mid;
    if (nums[low] <= nums[mid]) {
      if (nums[low] <= target && target < nums[mid]) high = mid - 1;
      else low = mid + 1;
    } else if (nums[mid] < target && target <= nums[high]) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return -1;
}
""", [(([4, 5, 6, 7, 0, 1, 2], 0), 4), (([4, 5, 6, 7, 0, 1, 2], 3), -1), (([1], 0), -1), (([3, 1], 1), 1), (([5, 1, 3], 5), 0)]),

    problem(22, "coin-change", "Coin Change", "medium", ["Dynamic Programming"], "coin_change", ["coins", "amount"], """
Given coin values `coins` (as many of each as you like) and an `amount`, return the fewest coins that add up to `amount`, or `-1` if it can't be made.""",
            ["1 ≤ coins.length ≤ 12", "1 ≤ coins[i] ≤ 2³¹ − 1", "0 ≤ amount ≤ 10⁴"],
            ["Greedy (largest coin first) fails for coins like [1, 3, 4] and amount 6.", "fewest(x) = 1 + the smallest fewest(x − coin)."],
            """Build a table: `best[x]` is the fewest coins for amount x, with best[0] = 0. For each x from 1 up, try every coin c ≤ x: best[x] = min(best[x], best[x − c] + 1). Amounts that stay unreachable keep a value bigger than any real answer.""",
            "Time O(amount × coins), space O(amount)", """
def coin_change(coins, amount):
    best = [0] + [amount + 1] * amount
    for value in range(1, amount + 1):
        for coin in coins:
            if coin <= value:
                best[value] = min(best[value], best[value - coin] + 1)
    return best[amount] if best[amount] <= amount else -1
""", """
function coinChange(coins, amount) {
  const best = new Array(amount + 1).fill(amount + 1);
  best[0] = 0;
  for (let value = 1; value <= amount; value++) {
    for (const coin of coins) {
      if (coin <= value) best[value] = Math.min(best[value], best[value - coin] + 1);
    }
  }
  return best[amount] <= amount ? best[amount] : -1;
}
""", [(([1, 2, 5], 11), 3, "5 + 5 + 1"), (([2], 3), -1), (([1], 0), 0), (([2, 5, 10, 1], 27), 4), (([186, 419, 83, 408], 6249), 20)]),

    problem(23, "merge-intervals", "Merge Intervals", "medium", ["Array", "Sorting"], "merge_intervals", ["intervals"], """
Each interval is `[start, end]`. Merge every set of overlapping intervals (touching counts as overlapping), and return the result sorted by start.""",
            ["1 ≤ intervals.length ≤ 10⁴", "0 ≤ start ≤ end ≤ 10⁴"],
            ["Sort by start: overlaps then sit next to each other."],
            """Sort by start. Walk through: if an interval starts before the last merged one ends, extend that one's end; otherwise start a new merged interval.""",
            "Time O(n log n), space O(n)", """
def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged
""", """
function mergeIntervals(intervals) {
  const merged = [];
  for (const [start, end] of [...intervals].sort((a, b) => a[0] - b[0])) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  return merged;
}
""", [(([[1, 3], [2, 6], [8, 10], [15, 18]],), [[1, 6], [8, 10], [15, 18]], "[1, 3] and [2, 6] overlap, so they become [1, 6]"), (([[1, 4], [4, 5]],), [[1, 5]]),
      (([[1, 4], [0, 4]],), [[0, 4]]), (([[1, 4], [2, 3]],), [[1, 4]])]),

    problem(24, "number-of-islands", "Number of Islands", "medium", ["Matrix", "Depth-First Search", "Breadth-First Search"], "num_islands", ["grid"], """
`grid` is a map of `"1"` (land) and `"0"` (water). An island is land connected up, down, left or right. Count the islands.""",
            ["1 ≤ rows, columns ≤ 300", "Cells are \"0\" or \"1\""],
            ["When you find unvisited land, it's a new island: mark all the land it connects to as visited."],
            """Scan every cell. On land you haven't visited, count a new island and flood out from it with a stack (or recursion), marking each connected land cell as visited so it isn't counted again.""",
            "Time O(rows × columns), space O(rows × columns)", """
def num_islands(grid):
    rows, cols = len(grid), len(grid[0]) if grid else 0
    seen = set()
    islands = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == "1" and (r, c) not in seen:
                islands += 1
                seen.add((r, c))
                stack = [(r, c)]
                while stack:
                    y, x = stack.pop()
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < rows and 0 <= nx < cols and grid[ny][nx] == "1" and (ny, nx) not in seen:
                            seen.add((ny, nx))
                            stack.append((ny, nx))
    return islands
""", """
function numIslands(grid) {
  const rows = grid.length;
  const cols = rows ? grid[0].length : 0;
  const seen = new Set();
  let islands = 0;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (grid[r][c] !== "1" || seen.has(`${r},${c}`)) continue;
      islands++;
      seen.add(`${r},${c}`);
      const stack = [[r, c]];
      while (stack.length) {
        const [y, x] = stack.pop();
        for (const [dy, dx] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
          const ny = y + dy;
          const nx = x + dx;
          if (ny >= 0 && ny < rows && nx >= 0 && nx < cols && grid[ny][nx] === "1" && !seen.has(`${ny},${nx}`)) {
            seen.add(`${ny},${nx}`);
            stack.push([ny, nx]);
          }
        }
      }
    }
  }
  return islands;
}
""", [(([["1", "1", "1", "1", "0"], ["1", "1", "0", "1", "0"], ["1", "1", "0", "0", "0"], ["0", "0", "0", "0", "0"]],), 1),
      (([["1", "1", "0", "0", "0"], ["1", "1", "0", "0", "0"], ["0", "0", "1", "0", "0"], ["0", "0", "0", "1", "1"]],), 3), (([["1"]],), 1), (([["0"]],), 0),
      (([["1", "0", "1"], ["0", "1", "0"], ["1", "0", "1"]],), 5)]),

    problem(25, "daily-temperatures", "Daily Temperatures", "medium", ["Array", "Stack", "Monotonic Stack"], "daily_temperatures", ["temperatures"], """
For each day in `temperatures`, return how many days you'd wait for a warmer one, or `0` if no warmer day comes.""",
            ["1 ≤ temperatures.length ≤ 10⁵", "30 ≤ temperatures[i] ≤ 100"],
            ["Keep the days still waiting for a warmer one. A warm day answers every cooler day waiting on top."],
            """Keep a stack of days still waiting, with their temperatures falling from bottom to top. For each new day, pop every waiting day that's cooler and record the gap. Then push the new day.""",
            "Time O(n), space O(n)", """
def daily_temperatures(temperatures):
    answer = [0] * len(temperatures)
    waiting = []
    for day, temp in enumerate(temperatures):
        while waiting and temperatures[waiting[-1]] < temp:
            earlier = waiting.pop()
            answer[earlier] = day - earlier
        waiting.append(day)
    return answer
""", """
function dailyTemperatures(temperatures) {
  const answer = new Array(temperatures.length).fill(0);
  const waiting = [];
  for (let day = 0; day < temperatures.length; day++) {
    while (waiting.length && temperatures[waiting[waiting.length - 1]] < temperatures[day]) {
      const earlier = waiting.pop();
      answer[earlier] = day - earlier;
    }
    waiting.push(day);
  }
  return answer;
}
""", [(([73, 74, 75, 71, 69, 72, 76, 73],), [1, 1, 4, 2, 1, 1, 0, 0]), (([30, 40, 50, 60],), [1, 1, 1, 0]), (([30, 60, 90],), [1, 1, 0]),
      (([50],), [0]), (([70, 70, 70],), [0, 0, 0]), (([90, 80, 70, 100],), [3, 2, 1, 0])]),

    problem(26, "flatten-nested-list", "Flatten Nested List", "medium", ["Recursion", "Array"], "flatten", ["nested"], """
`nested` is a list whose items are numbers or more lists, nested to any depth. Return one flat list of all the numbers, in order.""",
            ["0 ≤ total values ≤ 10⁴", "Nesting depth ≤ 50"],
            ["A list inside the list is the same problem, smaller."],
            """Recursion: for each item, if it's a list, flatten it and add all of its values; otherwise add the item. An explicit stack works the same way without recursion.""",
            "Time O(n), space O(depth)", """
def flatten(nested):
    result = []
    for item in nested:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result
""", """
function flatten(nested) {
  const result = [];
  for (const item of nested) {
    if (Array.isArray(item)) result.push(...flatten(item));
    else result.push(item);
  }
  return result;
}
""", [(([1, [2, [3, 4]], 5],), [1, 2, 3, 4, 5]), (([],), []), (([[[]]],), []), (([[1], 2],), [1, 2])]),

    problem(27, "reverse-words-in-a-string", "Reverse Words in a String", "medium", ["String", "Two Pointers"], "reverse_words", ["s"], """
Return the words of `s` in reverse order, separated by single spaces. `s` may have spaces at the ends or several between words; the answer has none of those.""",
            ["1 ≤ s.length ≤ 10⁴", "s has letters, digits and spaces", "At least one word"],
            ["Split on runs of spaces, not on single spaces."],
            """Split the string into words, ignoring extra spaces, reverse the list, and join with single spaces. Doing it in place means reversing the whole string, then each word.""",
            "Time O(n), space O(n)", """
def reverse_words(s):
    return " ".join(reversed(s.split()))
""", """
function reverseWords(s) {
  return s.trim().split(/\\s+/).filter(Boolean).reverse().join(" ");
}
""", [(("the sky is blue",), "blue is sky the"), (("  hello world  ",), "world hello", "No spaces at the ends of the answer"), (("a good   example",), "example good a"),
      (("one",), "one")]),

    problem(28, "trapping-rain-water", "Trapping Rain Water", "hard", ["Array", "Two Pointers", "Dynamic Programming"], "trap", ["height"], """
`height` is an elevation map of bars, each 1 wide. Return how much rain water it traps.""",
            ["0 ≤ height.length ≤ 2·10⁴", "0 ≤ height[i] ≤ 10⁵"],
            ["Water above a bar is min(tallest bar to its left, tallest to its right) minus its height.", "The side with the shorter wall so far decides the water."],
            """Water over each bar is the lower of the highest wall on its left and right, minus the bar. With two pointers, move in from the side whose wall is lower: that side's water is already decided by its own running maximum.""",
            "Time O(n), space O(1)", """
def trap(height):
    low, high = 0, len(height) - 1
    left_max = right_max = water = 0
    while low < high:
        if height[low] < height[high]:
            left_max = max(left_max, height[low])
            water += left_max - height[low]
            low += 1
        else:
            right_max = max(right_max, height[high])
            water += right_max - height[high]
            high -= 1
    return water
""", """
function trap(height) {
  let low = 0;
  let high = height.length - 1;
  let leftMax = 0;
  let rightMax = 0;
  let water = 0;
  while (low < high) {
    if (height[low] < height[high]) {
      leftMax = Math.max(leftMax, height[low]);
      water += leftMax - height[low];
      low++;
    } else {
      rightMax = Math.max(rightMax, height[high]);
      water += rightMax - height[high];
      high--;
    }
  }
  return water;
}
""", [(([0, 1, 0, 2, 1, 0, 1, 3, 2, 1, 2, 1],), 6), (([4, 2, 0, 3, 2, 5],), 9), (([],), 0), (([1],), 0), (([5, 4, 1, 2],), 1)]),

    problem(29, "median-of-two-sorted-arrays", "Median of Two Sorted Arrays", "hard", ["Array", "Binary Search", "Divide and Conquer"], "find_median_sorted_arrays",
            ["nums1", "nums2"], """
Given two sorted lists `nums1` and `nums2`, return the median of all their values together. Take O(log(m + n)) time.""",
            ["0 ≤ m, n ≤ 1000", "1 ≤ m + n ≤ 2000", "Answers within 10⁻⁵ are accepted"],
            ["Merging is O(m + n). Instead, choose how many values come from the shorter list on the left of the median.", "Binary search that split."],
            """Binary search the shorter list for a split point i, with j = half − i from the other, so the left side holds half the values. The split is right when both left ends are ≤ both right ends; then the median comes from the edge values. Otherwise move i left or right.""",
            "Time O(log(min(m, n))), space O(1)", """
def find_median_sorted_arrays(nums1, nums2):
    if len(nums1) > len(nums2):
        nums1, nums2 = nums2, nums1
    m, n = len(nums1), len(nums2)
    half = (m + n + 1) // 2
    low, high = 0, m
    while low <= high:
        i = (low + high) // 2
        j = half - i
        left1 = nums1[i - 1] if i > 0 else float("-inf")
        right1 = nums1[i] if i < m else float("inf")
        left2 = nums2[j - 1] if j > 0 else float("-inf")
        right2 = nums2[j] if j < n else float("inf")
        if left1 <= right2 and left2 <= right1:
            if (m + n) % 2:
                return float(max(left1, left2))
            return (max(left1, left2) + min(right1, right2)) / 2
        if left1 > right2:
            high = i - 1
        else:
            low = i + 1
    return 0.0
""", """
function findMedianSortedArrays(nums1, nums2) {
  if (nums1.length > nums2.length) [nums1, nums2] = [nums2, nums1];
  const m = nums1.length;
  const n = nums2.length;
  const half = Math.floor((m + n + 1) / 2);
  let low = 0;
  let high = m;
  while (low <= high) {
    const i = Math.floor((low + high) / 2);
    const j = half - i;
    const left1 = i > 0 ? nums1[i - 1] : -Infinity;
    const right1 = i < m ? nums1[i] : Infinity;
    const left2 = j > 0 ? nums2[j - 1] : -Infinity;
    const right2 = j < n ? nums2[j] : Infinity;
    if (left1 <= right2 && left2 <= right1) {
      if ((m + n) % 2) return Math.max(left1, left2);
      return (Math.max(left1, left2) + Math.min(right1, right2)) / 2;
    }
    if (left1 > right2) high = i - 1;
    else low = i + 1;
  }
  return 0;
}
""", [(([1, 3], [2]), 2.0, "All values: [1, 2, 3], so the median is 2"), (([1, 2], [3, 4]), 2.5, "(2 + 3) / 2"), (([0, 0], [0, 0]), 0.0), (([], [1]), 1.0), (([2], []), 2.0)],
            compare="float"),

    problem(30, "edit-distance", "Edit Distance", "hard", ["String", "Dynamic Programming"], "min_distance", ["word1", "word2"], """
Return the fewest edits that turn `word1` into `word2`, where an edit inserts, deletes or replaces one character.""",
            ["0 ≤ word1.length, word2.length ≤ 500", "Lower-case English letters"],
            ["Let d[i][j] be the answer for the first i letters of word1 and the first j of word2.", "If the letters match, d[i][j] = d[i−1][j−1]; otherwise 1 + the best of the three edits."],
            """Dynamic programming over prefixes. d[i][j] = d[i−1][j−1] when the i-th and j-th letters match, otherwise 1 + min(replace d[i−1][j−1], delete d[i−1][j], insert d[i][j−1]). Only the previous row is needed at any time.""",
            "Time O(m × n), space O(n)", """
def min_distance(word1, word2):
    previous = list(range(len(word2) + 1))
    for i, a in enumerate(word1, 1):
        current = [i]
        for j, b in enumerate(word2, 1):
            current.append(previous[j - 1] if a == b else 1 + min(previous[j - 1], previous[j], current[j - 1]))
        previous = current
    return previous[-1]
""", """
function minDistance(word1, word2) {
  let previous = Array.from({ length: word2.length + 1 }, (_, j) => j);
  for (let i = 1; i <= word1.length; i++) {
    const current = [i];
    for (let j = 1; j <= word2.length; j++) {
      current.push(word1[i - 1] === word2[j - 1] ? previous[j - 1] : 1 + Math.min(previous[j - 1], previous[j], current[j - 1]));
    }
    previous = current;
  }
  return previous[word2.length];
}
""", [(("horse", "ros"), 3, "horse → rorse (replace h) → rose (delete r) → ros (delete e)"), (("intention", "execution"), 5), (("", "abc"), 3), (("abc", "abc"), 0),
      (("kitten", "sitting"), 3)]),

    problem(31, "longest-valid-parentheses", "Longest Valid Parentheses", "hard", ["String", "Stack", "Dynamic Programming"], "longest_valid_parentheses", ["s"], """
Given a string `s` of `(` and `)`, return the length of the longest substring of correctly matched parentheses.""",
            ["0 ≤ s.length ≤ 3·10⁴"],
            ["Keep a stack of positions, starting with -1 as the base before any valid run."],
            """Push positions of `(`. On `)`, pop: if the stack is now empty, this `)` can't match, so push its position as the new base; otherwise the current valid run reaches from the stack's top to here.""",
            "Time O(n), space O(n)", """
def longest_valid_parentheses(s):
    stack, best = [-1], 0
    for i, ch in enumerate(s):
        if ch == "(":
            stack.append(i)
        else:
            stack.pop()
            if not stack:
                stack.append(i)
            else:
                best = max(best, i - stack[-1])
    return best
""", """
function longestValidParentheses(s) {
  const stack = [-1];
  let best = 0;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "(") {
      stack.push(i);
    } else {
      stack.pop();
      if (!stack.length) stack.push(i);
      else best = Math.max(best, i - stack[stack.length - 1]);
    }
  }
  return best;
}
""", [(("(()",), 2), ((")()())",), 4, '"()()"'), (("",), 0), (("()(()",), 2), (("()(())",), 6)]),

    problem(32, "sliding-window-maximum", "Sliding Window Maximum", "hard", ["Array", "Sliding Window", "Monotonic Queue"], "max_sliding_window", ["nums", "k"], """
A window of size `k` slides across `nums` one step at a time. Return the largest value in each window position.""",
            ["1 ≤ k ≤ nums.length ≤ 10⁵"],
            ["Keep positions whose values are falling. A new larger value makes the smaller ones behind it useless."],
            """Keep a queue of positions with falling values. For each new value, drop smaller values from the back, add its position, and drop the front if it slid out of the window. The front is always the window's maximum.""",
            "Time O(n), space O(k)", """
from collections import deque


def max_sliding_window(nums, k):
    window, out = deque(), []
    for i, n in enumerate(nums):
        while window and nums[window[-1]] <= n:
            window.pop()
        window.append(i)
        if window[0] <= i - k:
            window.popleft()
        if i >= k - 1:
            out.append(nums[window[0]])
    return out
""", """
function maxSlidingWindow(nums, k) {
  const window = [];
  const out = [];
  for (let i = 0; i < nums.length; i++) {
    while (window.length && nums[window[window.length - 1]] <= nums[i]) window.pop();
    window.push(i);
    if (window[0] <= i - k) window.shift();
    if (i >= k - 1) out.push(nums[window[0]]);
  }
  return out;
}
""", [(([1, 3, -1, -3, 5, 3, 6, 7], 3), [3, 3, 5, 5, 6, 7]), (([1], 1), [1]), (([9, 11], 2), [11]), (([4, -2], 2), [4]), (([1, 3, 1, 2, 0, 5], 3), [3, 3, 2, 5])]),

    problem(33, "n-queens-ii", "N-Queens II", "hard", ["Backtracking"], "total_n_queens", ["n"], """
Place `n` queens on an `n × n` chessboard so that no two attack each other (same row, column or diagonal). Return the number of different ways.""",
            ["1 ≤ n ≤ 9"],
            ["Place one queen per row, trying each column.", "Track used columns and both diagonals: row − col and row + col."],
            """Backtracking row by row. For each column, skip it if its column or either diagonal is taken (diagonals are identified by row − col and row + col); otherwise place a queen and continue with the next row. Count the boards that reach the last row.""",
            "Time O(n!), space O(n)", """
def total_n_queens(n):
    def place(row, cols, diagonals, anti):
        if row == n:
            return 1
        count = 0
        for col in range(n):
            if col in cols or row - col in diagonals or row + col in anti:
                continue
            count += place(row + 1, cols | {col}, diagonals | {row - col}, anti | {row + col})
        return count
    return place(0, set(), set(), set())
""", """
function totalNQueens(n) {
  const place = (row, cols, diagonals, anti) => {
    if (row === n) return 1;
    let count = 0;
    for (let col = 0; col < n; col++) {
      if (cols.has(col) || diagonals.has(row - col) || anti.has(row + col)) continue;
      count += place(row + 1, new Set([...cols, col]), new Set([...diagonals, row - col]), new Set([...anti, row + col]));
    }
    return count;
  };
  return place(0, new Set(), new Set(), new Set());
}
""", [((4,), 2, "There are two ways on a 4 × 4 board"), ((1,), 1), ((5,), 10), ((6,), 4), ((8,), 92)]),
]

BY_SLUG = {item["slug"]: item for item in PROBLEMS}
TOPICS = sorted({topic for item in PROBLEMS for topic in item["topics"]})
LABELS = dict(DIFFICULTIES)


def of_the_day(day):
    """The same problem for everyone on a given day, working through the set in a shuffled but fixed order."""
    return PROBLEMS[(day.toordinal() * 7) % len(PROBLEMS)]


def inline_code(text):
    """`code` in a statement, for the template (escaped first)."""
    from django.utils.html import escape
    from django.utils.safestring import mark_safe
    return mark_safe(re.sub(r"`([^`]+)`", r"<code>\1</code>", escape(text)))
