from WebCrawler_x import *

#todo 没有检测到 page,传递最后一页 xpath，参数custom_base_path
pages1, total1 = get_page_info('https://gitee.com/explore/all?page=1',custom_base_path='//*[@id="git-discover-page"]/a[5]/@href')
print(pages1, total1)


links=get_scrolling_page('https://news.qq.com/ch/tech',max_scrolls=4,required_fields=['adChannelId=tech'])
print(links)


pages, total = get_page_info('https://www.procell.com.cn/search-category=cell-resource-banks?page=2',mode='d')
print(pages, total)
