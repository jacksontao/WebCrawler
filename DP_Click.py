from WebCrawler_x import *
import concurrent.futures
import time
from DrissionPage import ChromiumOptions, ChromiumPage
from loguru import logger



def parse_item(url):
    article_dit=get_article(url)
    print(article_dit)



def DP_click(url, head, text=None, mode=None,xpath=None,pages=None,port=18080):
    if head:
        co = ChromiumOptions()
        co.auto_port(True)
        # co.set_proxy(proxy=f'http:127.0.0.1:{port}')
    else:
        logger.info('headless模式')
        co = ChromiumOptions().headless(True)
        co.auto_port(True)
        # co.set_proxy(proxy=f'http:127.0.0.1:{port}')

    page = ChromiumPage(co)

    try:
        page.get(url, retry=3, interval=1, timeout=10)

        # 滚动模式
        if mode == "scroll":
            logger.info('scroll模式')
            previous_height = 0
            scroll_attempts = 0
            while scroll_attempts < 200:
                page.scroll.to_bottom()
                time.sleep(1)
                logger.info(f'loading data: {scroll_attempts + 1} 次，等待 1s')

                links = get_links(url=url, html=page.html, xpath=xpath)
                if links:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                        executor.map(parse_item, links)

                current_height = page.run_js("return document.body.scrollHeight")
                try:
                    page.actions.click(f'{text}')
                except Exception as e:
                    logger.error(f'没有加载更多按钮{e}')
                    break
                if current_height > previous_height:
                    previous_height = current_height
                    scroll_attempts += 1
                else:
                    logger.info('滚动到底部')
                    break
        elif mode == "next_page":
            logger.info('next_page模式')
            click_time = 0
            while click_time < pages:
                time.sleep(1)
                logger.info(f'loading data: {click_time + 1} 次，等待 1s')
                click_time += 1
                links = get_links(url=url, html=page.html, xpath=xpath)
                if links:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                        executor.map(parse_item, links)
                try:
                    page.actions.click(f'{text}')
                except Exception as e:
                    logger.error(f'没有加载更多按钮{e}')
                    break
    finally:
        page.close()


if __name__ == '__main__':
    DP_click(url='https://zhonghua.gmw.cn/news.htm?q=deepseek', head=False, text="下一页", mode="next_page", xpath='//h3/a/@href',pages=2)
