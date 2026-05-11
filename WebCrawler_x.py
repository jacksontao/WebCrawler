"""WebCrawler - 实战级网页爬虫工具库

提供通用的网页爬取、解析、分页提取等功能
支持多线程、自动重试、URL去重、内容清洗等特性
"""

import hashlib
import json
import os
import random
import re
import threading
import time
import warnings
from collections import deque
from concurrent.futures import as_completed
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any, Callable
from urllib.parse import urljoin, urlparse, parse_qs, urlunparse

import pickle
warnings.filterwarnings('ignore', message=r'.*doesn\'t match a supported version.*')
import requests
import retrying
from bs4 import BeautifulSoup
from DrissionPage import WebPage
from DrissionPage._configs.chromium_options import ChromiumOptions
from DrissionPage._pages.chromium_page import ChromiumPage
from fake_useragent import UserAgent
from gne import GeneralNewsExtractor
from htmldate import find_date
from loguru import logger
from lxml import etree
from lxparse import LxParse
from pybloom_live import BloomFilter
from requests import RequestsDependencyWarning

warnings.filterwarnings('ignore', category=SyntaxWarning)
warnings.filterwarnings('ignore', category=RequestsDependencyWarning)

headers = {'user-agent': str(UserAgent().random)}


def run_in_threads(func, datas, max_workers=10, rate_limit=None, retries=3, retry_delay=1, batch_size=None,
                   batch_delay=0):
    """
    多线程运行函数，支持速率限制 & 自动重试 & 日志输出进度 & 批量执行
    Args:
        func (callable): 需要执行的函数，接受一个参数
        datas (iterable | list): 数据列表或可迭代对象 (如 Mongo cursor)
        max_workers (int): 最大线程数
        rate_limit (None | int | tuple):
            - None: 不限速
            - int: 每秒最多执行多少任务（固定速率）
            - tuple(min, max): 每秒任务数范围，随机选择速率
        retries (int): 每个任务失败后重试次数
        retry_delay (int | float): 重试间隔（秒）
        batch_size (None | int): 每批任务的数量（None 表示不分批）
        batch_delay (int | float): 每批之间的等待时间（秒）

    Returns:
        list: 按输入顺序对应的结果列表，失败时返回 Exception
    """
    datas = list(datas)
    total = len(datas)
    results = [None] * total
    lock = threading.Lock()
    last_time = [0.0]
    finished = 0

    def wrapper(data):
        if rate_limit:
            with lock:
                if isinstance(rate_limit, tuple):
                    rate = random.uniform(*rate_limit)
                else:
                    rate = rate_limit
                interval = 1.0 / rate
                elapsed = time.time() - last_time[0]
                if elapsed < interval:
                    time.sleep(interval - elapsed)
                last_time[0] = time.time()

        for attempt in range(1, retries + 1):
            try:
                return func(data)
            except Exception as e:
                if attempt < retries:
                    logger.warning(f"任务失败，重试 {attempt}/{retries} 次后继续: {e}")
                    time.sleep(retry_delay * attempt)
                else:
                    logger.error(f"任务最终失败: {e}")
                    return e

    for start in range(0, total, batch_size or total):
        end = min(start + (batch_size or total), total)
        batch = datas[start:end]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {executor.submit(wrapper, d): i for i, d in enumerate(batch, start)}
            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                results[idx] = future.result()
                finished += 1
                logger.info(f"进度: {finished}/{total} ({finished / total:.0%})")

        if end < total and batch_delay > 0:
            logger.info(f"批次完成 {end}/{total}，等待 {batch_delay}s 再继续...")
            time.sleep(batch_delay)

    return results


def is_content_page(url, base_domain):
    parsed_url = urlparse(url)

    domain = urlparse(base_domain).netloc
    if parsed_url.netloc != domain:
        return None

    path = parsed_url.path
    query = parsed_url.query

    slash_count = path.count("/")

    has_extension = bool(re.search(r'\.(html|php|asp|aspx|jsp|htm|shtml)$', path, re.IGNORECASE))

    has_numeric_id = bool(re.search(r'/\d{4,}', path)) or bool(re.search(r'id=\d+', query))

    is_list_url = not has_extension and (path.endswith("/") or slash_count < 3)

    list_keywords = ["category", "list", "news", "page", "archives", "tags"]
    contains_list_keyword = any(kw in path.lower() for kw in list_keywords)

    if has_extension or has_numeric_id:
        return url, True
    if is_list_url or contains_list_keyword:
        return url, False

    return url, False


def categorize_urls(urls, base_domain):
    """分类URL为内容页和列表页"""
    content_page, list_page = [], []
    for url in urls:
        result = is_content_page(url, base_domain)
        if result:
            if result[1] == True:
                content_page.append(result[0])
            elif result[1] == False:
                list_page.append(result[0])
    return content_page, list_page


class URLFilter:
    def __init__(self, capacity=1000000, error_rate=0.001, file_path='url_filter.pkl'):
        """
        初始化URL过滤器
        :param capacity: 布隆过滤器容量
        :param error_rate: 误判率
        :param file_path: 过滤器保存的文件路径
        """
        self.file_path = file_path
        self.capacity = capacity
        self.error_rate = error_rate
        self.bf = self.load_filter()

    def load_filter(self):
        """
        从文件加载过滤器，如果文件不存在或为空则新建一个并保存到文件
        :return: 加载的布隆过滤器
        """
        if not os.path.exists(self.file_path) or os.path.getsize(self.file_path) == 0:
            print(f"文件 {self.file_path} 不存在或为空，新建布隆过滤器并保存")
            bf = BloomFilter(capacity=self.capacity, error_rate=self.error_rate)
            self.save_filter(bf)
            return bf

        with open(self.file_path, 'rb') as f:
            return pickle.load(f)

    def save_filter(self, bf=None):
        """
        将过滤器保存到文件
        :param bf: 要保存的布隆过滤器，默认为 self.bf
        """
        if bf is None:
            bf = self.bf
        with open(self.file_path, 'wb') as f:
            pickle.dump(bf, f)

    def is_url_new(self, url):
        """
        检查URL是否为新URL
        :param url: 要检查的URL
        :return: True表示是新URL，False表示已存在
        """
        if url not in self.bf:
            return True
        return False

    def save(self, url):
        self.bf.add(url)
        self.save_filter()


def get_page_info(url, page_param=None, step=1, first_num=1, mode='auto', max_attempts=10, use_cache=False,
                  cache_file=None, proxy=None, stop_max_attempt_number=3, sleep=1, has_index=False,
                  custom_base_path=None, use_drission=False, drission_sleep=0, page_mode='auto'):
    """
    智能获取分页信息，支持自动检测、直接解析和二分查找三种模式

    Args:
        url: 初始URL
        page_param: 页码参数名（可选，auto模式会自动检测）
        step: 页码步长
        first_num: 起始页码
        mode: 请求模式
            - 's': requests
            - 'd': DrissionPage/WebPage
            - 'auto': 自动优先 d，失败退化 s
        max_attempts: 二分查找最大尝试次数
        use_cache: 是否使用缓存
        cache_file: 缓存文件名
        proxy: 代理设置
        stop_max_attempt_number: 重试次数
        sleep: 重试间隔
        has_index: 是否首页包括页码
        custom_base_path: 自定义XPath提取尾页链接
        use_drission: 是否使用DrissionPage渲染获取第一页内容
        drission_sleep: DrissionPage渲染后的等待时间
        page_mode: 分页解析策略
            - 'auto': 自动先 direct 再 binary
            - 'direct': 直接解析尾页链接
            - 'binary': 二分查找最大页码

    Returns:
        Tuple[List[str], int]: (页面链接列表, 总页数)

    Examples:
        >>>
        >>> links, total = get_page_info('https://example.com/news')
        >>>
        >>>
        >>> links, total = get_page_info('https://example.com/news?page=1', page_param='page')
    """
    headers = {'user-agent': str(UserAgent().random)}
    if not cache_file:
        cache_file = 'total_pages_cache.json'
    request_mode = _normalize_mode(mode, use_drission)

    def auto_detect_page_param(url, html_content):
        """自动检测分页参数"""
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        common_page_params = ['page', 'p', 'pn', 'pageNum', 'pageNo', 'pg', 'currentPage']

        for param in common_page_params:
            if param in query_params:
                logger.info(f"✅ 自动检测到URL分页参数: {param}")
                return param

        body = etree.HTML(html_content)
        pagination_links = body.xpath(
            "//a[contains(@href, 'page') or contains(@href, '/p/') or contains(@class, 'page')]/@href")

        for link in pagination_links[:5]:
            if match := re.search(r'/(page|p)/\d+', link):
                logger.info(f"✅ 自动检测到路径分页参数: /{match.group(1)}/")
                return f'/{match.group(1)}/'
            if match := re.search(r'_(\d+)\.html?$', link):
                logger.info(f"✅ 自动检测到文件名分页模式")
                return '_'

        logger.warning("⚠️ 未能自动检测分页参数，将尝试通用解析")
        return None

    def extract_base_url(url, page_param):
        """提取基础URL（去除页码部分）"""
        if not page_param:
            return url.split('?')[0]

        if page_param.startswith('/'):
            pattern = rf'(.*{re.escape(page_param)})\d+'
        else:
            pattern = rf'(.*[?&]{re.escape(page_param)}=)\d+'
        match = re.search(pattern, url)
        return match.group(1) if match else url.split('?')[0]

    @retrying.retry(wait_fixed=2000, stop_max_attempt_number=stop_max_attempt_number)
    def get_response_text(url, proxy=None):
        _mode = request_mode
        if _mode == 's':
            response = requests.get(url, headers=headers, proxies=proxy, timeout=10)
            if response.status_code == 200:
                response.encoding = response.apparent_encoding
                return response.text
            raise Exception(f"Status code {response.status_code}")

        if _mode == 'd':
            logger.info(f'使用DrissionPage获取内容: {url}')
            page = create_low_memory_page()
            try:
                page.get(url)
                time.sleep(drission_sleep)
                html = page.html or ''
                if not html.strip():
                    raise Exception('empty html from DrissionPage')
                return html
            finally:
                page.quit()

        try:
            response = requests.get(url, headers=headers, proxies=proxy, timeout=10)
            response.encoding = response.apparent_encoding
            text = response.text or ''
            if response.status_code == 200 and not _looks_like_blocked(response.status_code, text) and not _looks_js_heavy(text):
                logger.info(f'auto判定静态页，使用requests: {url}')
                return text
            logger.info(f'auto判定需浏览器渲染或被拦截，切换DrissionPage: {url}')
        except Exception as e:
            logger.warning(f'auto requests失败，切换DrissionPage: {e}')

        page = create_low_memory_page()
        try:
            page.get(url)
            time.sleep(drission_sleep)
            html = page.html or ''
            if html.strip():
                return html
            logger.warning(f'DrissionPage返回空HTML，回退requests: {url}')
        finally:
            page.quit()

        response = requests.get(url, headers=headers, proxies=proxy, timeout=10)
        response.encoding = response.apparent_encoding
        return response.text

    def load_cache():
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_cache(cache):
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)

    if use_cache:
        cache = load_cache()
        base_url = extract_base_url(url, page_param)
        cached_data = cache.get(base_url) or cache.get(url)
        if cached_data:
            logger.success(
                f"从缓存中读取: \nbase_url={base_url}\n总页数={cached_data['total_pages']}\n链接：{cached_data['all_pages_link'][:3]}...")
            return cached_data['all_pages_link'], cached_data['total_pages']
        else:
            logger.info("缓存中没有找到数据")

    response_text = get_response_text(url, proxy=proxy)

    if page_mode == 'auto':
        if not page_param:
            page_param = auto_detect_page_param(url, response_text)

        page_mode = 'direct'
        logger.info(f"🤖 自动模式：使用 direct 模式，page_param={page_param}")

    if page_mode == 'direct':
        body = etree.HTML(response_text)
        if custom_base_path:
            page_url = body.xpath(custom_base_path)
        else:
            page_url = body.xpath(
                "//a[text()='尾页' or text()='末页' or text()='最后一页' or text()='尾 页' or text()='未页']/@href")
            if not page_url and body is not None:
                page_links = body.xpath("//a[contains(@href, 'page=')]/@href")
                page_nums = []
                for link in page_links:
                    m = re.search(r'[?&]page=(\d+)', link)
                    if m:
                        page_nums.append(int(m.group(1)))
                if page_nums:
                    total_pages = max(page_nums)
                    if page_param:
                        base_without_query = url.split('?')[0]
                        sep = '&' if '?' in url else '?'
                        all_pages_link = [
                            f"{base_without_query}{sep}{page_param}={i}"
                            for i in range(first_num, total_pages + 1, step)
                        ]
                    else:
                        all_pages_link = [url]
                    logger.success(f"从分页a标签提取到总页数: {total_pages}")
                    logger.info(f"所有分页链接: {all_pages_link[:3]}...")
                    return all_pages_link, total_pages

        if not page_url:
            logger.info("未找到尾页链接")
            return [url], 1

        full_url = urljoin(url, page_url[0])
        if page_param:
            pattern = rf'(.*{page_param})(\d+)(\.[a-zA-Z0-9]+)?' if page_param.startswith(
                '/') else rf'(.*[?&]{page_param}=)(\d+)(\.[a-zA-Z0-9]+)?'
            match = re.search(pattern, full_url)
            if match:
                base_path = match.group(1)
                last_page_number = match.group(2)
                extension = match.group(3) or ''  # 文件扩展名（如 .html、.php 等）

                all_pages_link = [
                    f"{base_path}{(int(last_page_number) - i) * step + first_num}{extension}"
                    for i in range(int(last_page_number) - 1, -1, -1)
                ]
                all_pages_link.append(url)
                logger.success(f"基本路径: {base_path}, 页码: {last_page_number}, 扩展名: {extension}")
                logger.info(f"所有分页链接: {all_pages_link[:3]}...")
                return all_pages_link, int(last_page_number)

        match = re.match(r'(.*/)([^/]+?)_?(\d+)?_(\d+)(\.html)?', full_url)
        if match:
            base_path = f"{match.group(1)}{match.group(2)}_{match.group(3)}_{{}}{match.group(5) or '.html'}"
            current_page_number = int(match.group(4))
            main_id = match.group(3)

            if has_index:
                all_pages_link = [
                    base_path.format(page) for page in range(1, current_page_number + 1)
                ]
            else:
                all_pages_link = [
                    base_path.format(page) for page in range(2, current_page_number + 1)
                ]
                all_pages_link.append(full_url)

            logger.success(f"\n✅ 基本路径: {base_path}, 主编号: {main_id}, 页码: {current_page_number}")
            logger.info(f"\n✅所有分页链接预览: {all_pages_link[:3]}...")
            if use_cache:
                cache = load_cache()
                cache[url] = {
                    'total_pages': current_page_number,
                    'all_pages_link': all_pages_link
                }
                save_cache(cache)
                logger.success(f"结果已保存到缓存文件: {cache_file}")

            return all_pages_link, current_page_number
        else:
            logger.error("❌ 无法匹配链接格式")
            if page_mode != 'auto':
                return [url], 1
            page_mode = 'binary'

    if page_mode == 'binary' or page_mode == 'auto':
        def is_page_valid(page_url):
            try:
                if request_mode in ('d', 'auto'):
                    try:
                        page = create_low_memory_page()
                        try:
                            page.get(page_url)
                            time.sleep(drission_sleep)
                            valid = page.status_code == 200 if hasattr(page, 'status_code') else True
                            logger.info(f"📊是否是最后一页呢?: {page_url}")
                            return valid
                        finally:
                            page.quit()
                    except Exception:
                        if request_mode == 'd':
                            return False
                response = requests.get(page_url, headers=headers, proxies=proxy, timeout=10)
                logger.info(f"📊是否是最后一页呢?: {page_url}")
                return response.status_code == 200
            except Exception:
                return False

        def get_page_url(base_url, page_num, page_param):
            if not page_param: return base_url
            pattern = rf'(.*{page_param})(\d+)(\.[a-zA-Z0-9]+)?' if page_param.startswith(
                '/') else rf'(.*[?&]{page_param}=)(\d+)(\.[a-zA-Z0-9]+)?'
            match = re.search(pattern, base_url)
            if match:
                base_path = match.group(1)
                extension = match.group(3) or ''  # 文件扩展名
                return f'{base_path}{page_num}{extension}'
            else:
                if page_param.startswith('/'):
                    return f"{base_url.rstrip('/')}{page_param}{page_num}"
                else:
                    sep = '&' if '?' in base_url else '?'
                    return f"{base_url}{sep}{page_param}={page_num}"

        base_url_for_cache = extract_base_url(url, page_param)

        left, right = 1, 100
        attempts = 0
        while attempts < max_attempts:
            attempts += 1
            if is_page_valid(get_page_url(url, right, page_param)):
                left = right
                right *= 2
            else:
                break

        while left < right:
            mid = (left + right) // 2
            if is_page_valid(get_page_url(url, mid, page_param)):
                left = mid + 1
            else:
                right = mid
            time.sleep(sleep)

        total_pages = left - 1
        all_pages_link = [get_page_url(url, i, page_param) for i in range(1, total_pages + 1)]

        if use_cache:
            cache = load_cache()
            cache[f'{base_url_for_cache}'] = {
                'total_pages': total_pages,
                'all_pages_link': all_pages_link
            }
            save_cache(cache)
            logger.success(f"🎉最后一页:{get_page_url(url, total_pages, page_param)}")
            logger.success(f"✅ 结果已保存到缓存文件: {cache_file}，总页数: {total_pages}")

        return all_pages_link, total_pages

    raise ValueError("page_mode 只能是 'auto'、'direct' 或 'binary'")


def create_low_memory_page():
    co = ChromiumOptions().headless(True)

    for arg in [
        '--disable-dev-shm-usage',
        '--disable-software-rasterizer',
        '--disable-extensions',
        '--disable-default-apps',
        '--disable-popup-blocking',
        '--disable-notifications',
        '--disable-infobars',
        '--no-first-run',
        '--no-service-autorun',
        '--no-proxy-server',
        '--single-process',
        '--no-zygote',
        '--disable-renderer-backgrounding',
        '--disable-background-timer-throttling'
    ]:
        co.set_argument(arg)

    co.set_pref('profile.managed_default_content_settings.images', 2)


    return ChromiumPage(co)


def _normalize_mode(mode='auto', use_drission=False):
    """统一 mode 与 use_drission 兼容：s=request, d=DrissionPage/WebPage, auto=自动退化"""
    if mode not in ('s', 'd', 'auto', None):
        raise ValueError("mode 只能是 's'、'd' 或 'auto'")
    if mode in ('s', 'd'):
        return mode
    if use_drission:
        return 'd'
    return 'auto'


def _looks_like_blocked(status_code=None, html_text=''):
    text = (html_text or '').lower()
    if status_code in (401, 403, 429, 503):
        return True
    markers = ['captcha', 'verify', 'verification', 'waf', '访问受限', '人机验证', '安全验证', 'forbidden']
    return any(m in text for m in markers)


def _looks_js_heavy(html_text=''):
    text = html_text or ''
    lower = text.lower()
    if len(text.strip()) < 300:
        return True
    if '__next' in lower or 'id="app"' in lower or 'window.__' in lower:
        return True
    if lower.count('<script') >= 8 and lower.count('<a ') <= 2:
        return True
    return False


def get_links(url, xpath='', proxy=None, article_nums=None, required_fields=None, base_url=None, regex=None,
              html=None, use_drission=False, sleep=1, mode='auto'):
    """
    提取页面中的链接

    Args:
        url: 目标URL
        xpath: XPath表达式，默认提取所有<a>标签的href
        proxy: 代理设置
        article_nums: 控制相似URL数量
        required_fields: 必须包含的字段列表（如 ['news', 'detail']）
        base_url: 基础URL，用于拼接相对路径
        regex: 正则表达式筛选URL
        html: 直接传入HTML内容
        use_drission: 是否使用DrissionPage渲染
        sleep: DrissionPage渲染等待时间

    Returns:
        List[str]: 筛选后的URL列表

    Examples:
        >>>
        >>> links = get_links('https://example.com/news')
        >>>
        >>>
        >>> links = get_links('https://example.com', xpath='//div[@class="article"]//a/@href')
        >>>
        >>>
        >>> links = get_links('https://example.com', regex=r'/article/\\d+')
    """

    def filter_by_fields(urls, required_fields, regex):
        """
        根据必须包含的字段和正则筛选 URL
        :param urls: URL 列表
        :param required_fields: 必须包含的字段列表
        :param regex: 正则表达式，如果不为空，则根据正则筛选 URL
        :return: 筛选后的 URL 列表
        """
        if not required_fields and not regex:
            return urls

        filtered_urls = []

        for url in urls:
            if required_fields and any(field in url for field in required_fields):
                filtered_urls.append(url)
            elif regex and re.match(regex, url):
                filtered_urls.append(url)

        return filtered_urls

    @retrying.retry(wait_fixed=2000, stop_max_attempt_number=3)
    def get_response(url, params=None, data=None, proxy=None):
        try:
            if data is None:
                if params is None:
                    response = requests.get(url, headers=headers, proxies=proxy, timeout=10, verify=False)
                else:
                    response = requests.get(url, headers=headers, params=params, proxies=proxy, timeout=10)
                if '20' in f'{response.status_code}':
                    response.encoding = response.apparent_encoding
                    return response
            else:
                if params is None:
                    response = requests.post(url, headers=headers, data=data, proxies=proxy, timeout=10)
                else:
                    response = requests.post(url, headers=headers, data=data, params=params, proxies=proxy, timeout=10)
                if '20' in f'{response.status_code}':
                    response.encoding = response.apparent_encoding
                    return response
        except Exception as e:
            logger.info(f'抓取失败,重新抓取：{url}')
            logger.info(f'error:{e}')
            raise

    try:
        lx = LxParse()
        if html != None:
            response = html
        else:
            _mode = _normalize_mode(mode, use_drission)
            if _mode == 's':
                response = get_response(url, proxy=proxy)
                if response is None:
                    logger.error(f'抓取失败，返回 None: {url}')
                    return []
                response = response.text
            elif _mode == 'd':
                logger.info('使用DrissionPage')
                page = create_low_memory_page()
                page.get(url, retry=1, timeout=3)
                time.sleep(sleep)
                response = page.html
                page.quit()
                if not (response or '').strip():
                    raise Exception(f'DrissionPage返回空HTML: {url}')
            else:
                req_resp = None
                try:
                    req_resp = get_response(url, proxy=proxy)
                    if req_resp is not None:
                        req_html = req_resp.text or ''
                        if not _looks_like_blocked(getattr(req_resp, 'status_code', None), req_html) and not _looks_js_heavy(req_html):
                            logger.info(f'auto判定静态页，使用requests: {url}')
                            response = req_html
                        else:
                            raise Exception('requests命中验证/重JS页')
                    else:
                        raise Exception('requests返回None')
                except Exception as e:
                    logger.info(f'auto切换DrissionPage: {e}')
                    try:
                        page = create_low_memory_page()
                        page.get(url, retry=1, timeout=3)
                        time.sleep(sleep)
                        response = page.html
                        page.quit()
                        if not (response or '').strip():
                            raise Exception('DrissionPage空HTML')
                    except Exception as de:
                        logger.warning(f'DrissionPage失败，回退requests: {de}')
                        if req_resp is None:
                            req_resp = get_response(url, proxy=proxy)
                        if req_resp is None:
                            logger.error(f'抓取失败，返回 None: {url}')
                            return []
                        response = req_resp.text

        if article_nums is not None:
            detail_url_list = lx.parse_list(response, article_nums=article_nums, xpath_list=xpath)
        elif xpath:
            detail_url_list = lx.parse_list(response, xpath_list=xpath)
        else:
            detail_url_list = lx.parse_list(response)

        if base_url:
            urls = [urljoin(base_url, detail_url) for detail_url in detail_url_list]
        else:
            urls = [urljoin(url, detail_url) for detail_url in detail_url_list]

        if required_fields or regex:
            urls = filter_by_fields(urls, required_fields, regex)

        if len(urls) > 0:
            logger.success(f"url:{url}；解析出链接{len(urls)}条")
            return list(set(urls))
        else:
            logger.error(f"url:{url}；未解析到链接,可传入xpath")
            return []

    except Exception as e:
        logger.error(f'解析失败:{e}')
        pass


@retrying.retry(wait_fixed=1000, stop_max_attempt_number=3)
def get_article(url, proxy=None, parsing_mode='lx', headers=headers, Filter=False, url_filter=None, use_drission=False,
                xpath_item=None, sleep=0, cookies=None, html=None, mode='auto'):
    """
    提取文章内容

    Args:
        url: 文章URL
        proxy: 代理设置
        parsing_mode: 解析模式
            - 'lx': 使用lxparse解析（默认）
            - 'gne': 使用GeneralNewsExtractor解析
            - 'xpath': 使用自定义XPath解析
        headers: 请求头
        Filter: 是否启用URL去重
        url_filter: URL过滤器实例
        use_drission: 是否使用DrissionPage渲染
        xpath_item: 自定义XPath配置字典
            - xpath_title: 标题XPath
            - xpath_source: 来源XPath
            - xpath_date: 日期XPath
            - xpath_author: 作者XPath
            - xpath_content: 内容XPath
        sleep: DrissionPage渲染等待时间
        cookies: 请求cookies
        html: 直接传入HTML内容

    Returns:
        Dict: 文章信息字典
            - title: 标题
            - content: 正文
            - author: 作者
            - publish_time: 发布时间
            - url: 原始URL
            - _id: 唯一ID（MD5）
            - updateTime: 更新时间
            - addDateTime: 添加时间

    Examples:
        >>>
        >>> article = get_article('https://example.com/news/123')
        >>> print(article['title'], article['content'])
        >>>
        >>>
        >>> xpath_config = {
        ...     'xpath_title': '//h1[@class="title"]/text()',
        ...     'xpath_content': '//div[@class="content"]//text()'
        ... }
        >>> article = get_article(url, parsing_mode='xpath', xpath_item=xpath_config)
    """


    def clean_text_bs(html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        return soup.get_text()

    def clean_text_regex(text):
        return re.sub(r'\s+', ' ', text).strip()

    try:
        dit = {}
        if html != None:
            response = html
        else:
            _mode = _normalize_mode(mode, use_drission)
            if _mode == 's':
                resp = requests.get(url, headers=headers, proxies=proxy, timeout=5, verify=False, cookies=cookies)
                resp.encoding = resp.apparent_encoding
                response = resp.text
            elif _mode == 'd':
                co = ChromiumOptions()
                if proxy and proxy.get('http'):
                    co.set_proxy(proxy['http'])
                tab = WebPage(chromium_options=co)
                tab.get(url)
                time.sleep(sleep)
                response = tab.html
                dit['html'] = response
                if not (response or '').strip():
                    raise Exception('DrissionPage空HTML')
            else:
                req_html = None
                try:
                    resp = requests.get(url, headers=headers, proxies=proxy, timeout=5, verify=False, cookies=cookies)
                    resp.encoding = resp.apparent_encoding
                    req_html = resp.text or ''
                    if not _looks_like_blocked(resp.status_code, req_html) and not _looks_js_heavy(req_html):
                        logger.info(f'auto判定静态详情页，使用requests: {url}')
                        response = req_html
                    else:
                        raise Exception('requests命中验证/重JS详情页')
                except Exception as e:
                    logger.info(f'auto切换DrissionPage详情页: {e}')
                    try:
                        co = ChromiumOptions()
                        if proxy and proxy.get('http'):
                            co.set_proxy(proxy['http'])
                        tab = WebPage(chromium_options=co)
                        tab.get(url)
                        time.sleep(sleep)
                        response = tab.html
                        dit['html'] = response
                        if not (response or '').strip():
                            raise Exception('DrissionPage空HTML')
                    except Exception as de:
                        logger.warning(f'DrissionPage失败，回退requests详情页: {de}')
                        if req_html is None:
                            resp = requests.get(url, headers=headers, proxies=proxy, timeout=5, verify=False, cookies=cookies)
                            resp.encoding = resp.apparent_encoding
                            req_html = resp.text
                        response = req_html

        if Filter and url_filter and not url_filter.is_url_new(url):
            logger.info(f'请求已存在，跳过: {url}')
            return

        extractor = GeneralNewsExtractor()
        result_gne = extractor.extract(response)
        lx = LxParse()

        result = lx.parse_detail(response)
        _id = hashlib.md5(url.encode('utf-8')).hexdigest()

        dit['title'] = result.get('title', '').strip()
        if parsing_mode == 'lx':
            dit['author'] = result.get('author', '').strip()
            dit['html'] = response
            dit['content'] = clean_text_regex(result.get('content_format', ''))

        elif parsing_mode == 'gne':
            dit['html'] = response
            dit['author'] = result_gne.get('author', '').strip()
            dit['content'] = clean_text_bs(clean_text_regex(result_gne.get('content', '')))

            dit['html'] = response
        elif parsing_mode == 'xpath' and xpath_item:
            dit['title'] = clean_text_regex(lx.parse_detail(str(response), xpath_item['xpath_title']))
            dit['content'] = clean_text_regex(lx.parse_detail(str(response), xpath_item['xpath_content']))
        dit['updateTime'] = str(datetime.now())[:19]
        dit['addDateTime'] = str(datetime.now())[:19]
        dit['publish_time'] = find_date(response)
        dit['_id'] = _id
        dit['url'] = url
        if len(dit['content']) > 0:
            return dit
        else:
            logger.error(f'内容为空: {url}')
            return None
    except Exception as e:
        logger.error(f'重新抓取：{url} ，出错了')
        logger.error(f'error:{e}')
        raise


def get_scrolling_page(url, row_xpath='//a/@href', max_scrolls=5, wait=1.0, proxy=None, base_url=None,
                       required_fields=None, regex=None, mode='auto', use_drission=False):
    """
    滚动页抓取链接：s=request(单页) / d=DrissionPage滚动 / auto=自动退化
    """
    _mode = _normalize_mode(mode, use_drission)
    base_url = base_url or url

    def _filter(urls):
        out = []
        for u in urls:
            if required_fields and not any(k in u for k in required_fields):
                continue
            if regex and not re.match(regex, u):
                continue
            out.append(u)
        return list(set(out))

    if _mode == 's':
        return get_links(url, xpath=row_xpath, proxy=proxy, base_url=base_url, required_fields=required_fields,
                         regex=regex, mode='s')

    if _mode == 'auto':
        try:
            resp = requests.get(url, headers=headers, proxies=proxy, timeout=10, verify=False)
            resp.encoding = resp.apparent_encoding
            req_html = resp.text or ''
            if resp.status_code == 200 and not _looks_like_blocked(resp.status_code, req_html) and not _looks_js_heavy(req_html):
                logger.info(f'auto判定静态滚动页，直接requests: {url}')
                return get_links(url, xpath=row_xpath, proxy=proxy, base_url=base_url,
                                 required_fields=required_fields, regex=regex, html=req_html, mode='s')
        except Exception:
            pass
        try:
            return get_scrolling_page(url, row_xpath=row_xpath, max_scrolls=max_scrolls, wait=wait, proxy=proxy,
                                      base_url=base_url, required_fields=required_fields, regex=regex, mode='d')
        except Exception as e:
            logger.warning(f'滚动模式失败，降级s模式: {e}')
            return get_scrolling_page(url, row_xpath=row_xpath, max_scrolls=max_scrolls, wait=wait, proxy=proxy,
                                      base_url=base_url, required_fields=required_fields, regex=regex, mode='s')

    page = create_low_memory_page()
    try:
        page.get(url)
        time.sleep(wait)
        links = set()
        for _ in range(max_scrolls + 1):
            logger.info(f'滚动抓取: {url}，当前链接数: {len(links)}，滚动次数: {_}')
            html = page.html or ''
            body = etree.HTML(html)
            if body is not None:
                raw = body.xpath(row_xpath) or []
                links.update(urljoin(base_url, x) for x in raw if x)
            page.scroll.to_bottom()
            time.sleep(wait)
        if not links:
            raise Exception('DrissionPage滚动后未提取到任何链接')
        return _filter(list(links))
    finally:
        try:
            page.quit()
        except Exception:
            pass



def is_valid_data(content):
    """
    验证内容是否有效

    检查项：
    1. 内容是否为空
    2. 是否包含版权声明/404等无效内容
    3. 是否包含大量乱码字符
    4. 中文字符比例是否达标

    Args:
        content: 待验证的文本内容

    Returns:
        bool: True表示内容有效，False表示应该丢弃

    Examples:
        >>> content = "这是一篇正常的文章内容..."
        >>> if is_valid_data(content):
        ...     save_to_database(content)
    """
    COPYRIGHT_PATTERNS = [
        r'版权所有',
        r'滑块验证',
        r'©\s*\d{4}',
        r'All rights reserved',
        r'Copyright\s*\d{4}',
        r'copyright',
        r'页面没有找到',
        r'互联网新闻信息许可证',
        r'备案号',
        r'凡注有',
        r'特别声明',
        r'404',
        r'找不到文件或目录',
    ]
    ABNORMAL_PATTERN = r'[�\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]'
    if not content:
        logger.error("内容为空")
        return False
    for pattern in COPYRIGHT_PATTERNS:
        if re.search(pattern, content):
            return False
    abnormal_count = len(re.findall(ABNORMAL_PATTERN, content))
    abnormal_ratio = abnormal_count / len(content) if len(content) > 0 else 1
    if abnormal_ratio > 0.1:
        logger.error(f"异常字符过多 ({abnormal_ratio:.2%})，丢弃数据,content:{content}")
        return False
    if abnormal_count > 0:
        content = re.sub(ABNORMAL_PATTERN, "", content)
        content = content
    chinese_chars = sum(1 for char in content if '\u4e00' <= char <= '\u9fff')
    chinese_ratio = chinese_chars / len(content)

    if chinese_ratio < 0.1:
        logger.error(f"中文比例过低: {chinese_ratio:.2%},content:{content}")
        return False

    return True


def search_links_stream(
        start_url: str,
        pattern: str,
        max_depth: int = 3,
        max_breadth: int = 5,
        batch_size: int = 50,
):
    """
    使用BFS+DFS策略搜索符合条件的链接

    Args:
        start_url: 起始URL
        pattern: 正则表达式匹配模式
        max_depth: 最大搜索深度
        max_breadth: 每层最大链接数
        batch_size: 批量返回大小

    Yields:
        List[str]: 符合条件的链接列表

    Examples:
        >>>
        >>> for batch in search_links_stream('https://example.com', r'/article/\\d+'):
        ...     print(f"找到 {len(batch)} 个链接")
        ...     for url in batch:
        ...         process_article(url)
    """
    visited = set()
    batch = []
    queue = deque([(start_url, 0)])
    while queue:
        url, depth = queue.popleft()
        if url in visited or depth > max_depth:
            continue
        visited.add(url)

        try:
            resp = requests.get(url, timeout=5, headers=headers, proxies=None, verify=False)
            if resp.status_code != 200:
                continue
            html = resp.text
            time.sleep(1)
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        links = [urljoin(url, a.get('href')) for a in soup.find_all('a', href=True)]
        for link in links:
            if re.search(pattern, link):
                batch.append(link)
                if len(batch) >= batch_size:
                    yield batch
                    batch = []

        next_depth = depth + 1
        if next_depth <= max_depth:
            limited_links = links[:max_breadth]
            for l in reversed(limited_links):
                queue.appendleft((l, next_depth))
    if batch:
        time.sleep(2)
        yield batch


class WebCrawler:
    """
    统一的网页爬虫类，封装常用的爬虫功能

    功能：
    - 自动分页检测和提取
    - 链接提取和过滤
    - 文章内容解析
    - URL去重
    - 多线程执行

    Attributes:
        base_url: 基础URL
        proxy: 代理设置
        headers: 请求头
        url_filter: URL过滤器

    Examples:
        >>>
        >>> crawler = WebCrawler('https://example.com')
        >>>
        >>>
        >>> pages, total = crawler.get_pages('/news')
        >>> print(f"找到 {total} 页")
        >>>
        >>>
        >>> links = crawler.extract_links(pages[0])
        >>>
        >>>
        >>> articles = crawler.get_articles(links, max_workers=5)
    """

    def __init__(self, base_url: str = None, proxy: dict = None, use_filter: bool = True,
                 filter_capacity: int = 1000000):
        """
        初始化爬虫

        Args:
            base_url: 基础URL，用于拼接相对路径
            proxy: 代理设置
            use_filter: 是否启用URL去重
            filter_capacity: 过滤器容量
        """
        self.base_url = base_url
        self.proxy = proxy
        self.headers = {'user-agent': str(UserAgent().random)}
        self.url_filter = URLFilter(capacity=filter_capacity) if use_filter else None
        logger.info(f"🚀 WebCrawler 初始化完成: base_url={base_url}")

    def get_pages(self, path: str = '', **kwargs) -> Tuple[List[str], int]:
        """
        自动提取分页链接

        Args:
            path: 路径（相对或绝对）
            **kwargs: 传递给 get_page_info 的其他参数

        Returns:
            Tuple[List[str], int]: (页面链接列表, 总页数)
        """
        url = urljoin(self.base_url, path) if self.base_url else path
        return get_page_info(url, proxy=self.proxy, **kwargs)

    def extract_links(self, url: str, **kwargs) -> List[str]:
        """
        提取页面链接

        Args:
            url: 目标URL
            **kwargs: 传递给 get_links 的其他参数

        Returns:
            List[str]: 链接列表
        """
        kwargs.setdefault('base_url', self.base_url)
        kwargs.setdefault('proxy', self.proxy)
        return get_links(url, **kwargs)

    def get_article(self, url: str, **kwargs) -> Optional[Dict]:
        """
        提取单个文章

        Args:
            url: 文章URL
            **kwargs: 传递给 get_article 的其他参数

        Returns:
            Dict: 文章信息字典
        """
        kwargs.setdefault('proxy', self.proxy)
        kwargs.setdefault('headers', self.headers)
        if self.url_filter:
            kwargs['Filter'] = True
            kwargs['url_filter'] = self.url_filter
        return get_article(url, **kwargs)

    def get_articles(self, urls: List[str], max_workers: int = 5, **kwargs) -> List[Dict]:
        """
        批量提取文章

        Args:
            urls: URL列表
            max_workers: 最大线程数
            **kwargs: 传递给 get_article 的其他参数

        Returns:
            List[Dict]: 文章信息列表
        """

        def fetch(url):
            return self.get_article(url, **kwargs)

        return run_in_threads(fetch, urls, max_workers=max_workers)

    def crawl_site(self, start_path: str = '', max_pages: int = None, **kwargs) -> List[Dict]:
        """
        爬取整个站点

        Args:
            start_path: 起始路径
            max_pages: 最大爬取页数
            **kwargs: 其他参数

        Returns:
            List[Dict]: 所有文章列表
        """
        logger.info("🔍 步骤 1: 提取分页链接...")
        pages, total = self.get_pages(start_path, **kwargs)
        if max_pages:
            pages = pages[:max_pages]
        logger.success(f"✅ 找到 {len(pages)} 个分页")

        logger.info("🔍 步骤 2: 提取文章链接...")
        all_links = []
        for page in pages:
            links = self.extract_links(page, **kwargs)
            all_links.extend(links)
        all_links = list(set(all_links))
        logger.success(f"✅ 找到 {len(all_links)} 个文章链接")

        logger.info("🔍 步骤 3: 提取文章内容...")
        articles = self.get_articles(all_links, **kwargs)
        articles = [a for a in articles if a and is_valid_data(a.get('content', ''))]
        logger.success(f"✅ 成功提取 {len(articles)} 篇有效文章")

        return articles



__all__ = [
    'WebCrawler',
    'URLFilter',

    'run_in_threads',
    'get_page_info',
    'get_links',
    'get_article',
    'search_links_stream',

    'is_content_page',
    'categorize_urls',
    'is_valid_data',
    'create_low_memory_page',
]



if __name__ == '__main__':
    logger.info("👋 WebCrawler 库加载成功！")
    logger.info("""
    基本使用示例：

    crawler = WebCrawler('https://example.com')
    pages, total = crawler.get_pages('/news')  # 自动检测分页

    links = crawler.extract_links(pages[0])

    articles = crawler.get_articles(links, max_workers=5)

    all_articles = crawler.crawl_site('/news', max_pages=10)
    """)
