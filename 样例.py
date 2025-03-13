import concurrent.futures
import re
import time
import jsonpath
import loguru
import requests
import retrying
from WebCrawler_x import *





@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
def get_page_urls(page):
    # curl获取的格式
    headrs={}
    params = {}
    response = requests.get(url, headers=headrs, params=params)
    # 正则获取的格式
    urls = re.findall(r'"artUrl":"(.*?)"', response.text.replace('\\', ''))
    # jsonpath获取的格式
    urls=jsonpath.jsonpath(response.json(), '$..url')
    if urls:
        return urls
    else:
        logger.error(f"第{page}页数据获取失败,")
        raise




@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
def parse_item(url):
    try:
        dit = get_article(url, proxy=proxy, Filter=True, url_filter=filter,parsing_mode='lx')
        print(dit)
    except Exception as e:
        logger.error(f"解析失败：{e}")
        raise




if __name__ == '__main__':
    filter=URLFilter()
    proxy=None
    logger=loguru.logger
    for i in range(1,2):
        try:
            logger.info(f"开始获取第{i}页数据")
            #json动态加载
            urls = get_page_urls(i)
            #有页数的url
            url=f'{i}'
            urls = get_links(url)
            if urls:
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    executor.map(parse_item, urls)
            else:
                print("未获取到数据")
                continue
            time.sleep(2)
        except Exception as e:
            logger.error(f"第{i}页数据获取失败：{e}")
            continue
