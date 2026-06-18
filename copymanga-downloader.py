import os
import re
import time
import random
import requests
from loguru import logger
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
    WebDriverException
)
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
# ==================== 全局配置 ====================
logger.add(
    "manga_download_log_{time}.log",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    rotation="10 MB",
    retention="7 days"
)
BASE_URL = "https://www.mangacopy.com/comic/漫画地址全称"
SAVE_ROOT = r"保存地址绝对路径"
DRIVER_PATH = r"msedgedriver.exe绝对路径"
MIN_DELAY = 1.2
MAX_DELAY = 2.2
PAGE_WAIT = 60
IMG_HEADERS = {
    "Referer": "https://www.mangacopy.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
}
INVALID_CHAR = str.maketrans(r'\/:*?"<>|', "_" * 9)
# XPATH配置
XPATH_CHAPTER_ITEM = "//main/div[2]/div[3]/div[1]/div[2]/div/div[1]/ul[1]/a"
XPATH_NEXT_PAGE_BTN = "//main/div[2]/div[3]/div[1]/div[2]/div/div[1]/ul[2]/li[4]/a"
XPATH_PAGE_NUM_TEXT = "//main/div[2]/div[3]/div[1]/div[2]/div/div[1]/ul[2]/li[1]/span"
# ==================== 工具函数 ====================
def random_delay(min_sec=MIN_DELAY, max_sec=MAX_DELAY):
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)
    logger.debug(f"随机延时 {delay:.2f}s")
def safe_mkdir(folder_path):
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        logger.debug(f"创建目录：{folder_path}")
def clean_folder_name(raw_title: str) -> str:
    return raw_title.translate(INVALID_CHAR).strip()
def parse_range_input(input_str: str, total_len: int):
    target_index = set()
    input_str = input_str.strip()
    # 空输入 = 全部下载
    if not input_str:
        return True, set(range(total_len))
    # 去除末尾多余逗号
    if input_str.endswith(","):
        input_str = input_str.rstrip(",")
    parts = input_str.split(",")
    valid_format = True
    for part in parts:
        part = part.strip()
        if not part:
            valid_format = False
            break
        if "-" in part:
            match = re.fullmatch(r"(\d+)-(\d+)", part)
            if not match:
                valid_format = False
                break
            start = int(match.group(1))
            end = int(match.group(2))
            start = max(1, start)
            end = min(total_len, end)
            for num in range(start, end + 1):
                target_index.add(num - 1)
        else:
            # 处理单个数字输入
            if not part.isdigit():
                valid_format = False
                break
            num = int(part)
            if 1 <= num <= total_len:
                target_index.add(num - 1)
            else:
                logger.warning(f"章节{num}超出范围(1~{total_len})，已忽略该数字")
    # 格式合法且存在有效章节才返回True
    if not valid_format or len(target_index) == 0:
        return False, set()
    return True, target_index
# ==================== 浏览器初始化 ====================
def init_browser():
    logger.info("开始初始化Edge浏览器（可视化窗口，反检测配置）")
    try:
        edge_options = Options()
        edge_options.add_experimental_option("useAutomationExtension", False)
        edge_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        edge_options.add_argument("--disable-blink-features=AutomationControlled")
        edge_options.add_argument("--no-sandbox")
        edge_options.add_argument("--disable-dev-shm-usage")
        edge_options.add_argument("--start-maximized")
        edge_options.add_argument("--disable-extensions")
        edge_options.add_argument("--ignore-certificate-errors")
        edge_options.add_argument("--auto-proxy-detect")
        edge_options.add_argument("--proxy-system-auth")
        edge_options.add_experimental_option("detach", True)
        edge_service = Service(executable_path=DRIVER_PATH)
        edge_service.log_path = "edge_driver.log"
        driver = webdriver.Edge(service=edge_service, options=edge_options)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh']});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            """
        })
        driver.set_page_load_timeout(PAGE_WAIT)
        driver.implicitly_wait(8)
        logger.info("Edge浏览器初始化完成，窗口已打开")
        return driver
    except Exception as e:
        logger.error(f"浏览器初始化失败：{str(e)}", exc_info=True)
        raise
# ==================== 抓取 ====================
def get_page_text(driver):
    try:
        elem = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, XPATH_PAGE_NUM_TEXT)))
        return elem.text.strip()
    except:
        return ""
def get_all_chapter_list(driver):
    logger.info(f"访问漫画主页：{BASE_URL}")
    driver.get(BASE_URL)
    random_delay(3, 4)
    logger.info("等待页面加载，如需登录/人机验证请手动操作，等待5秒")
    time.sleep(5)
    all_chapters = []
    logger.info("===== 读取章节 =====")
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    random_delay(1.5, 2.5)
    try:
        chapter_elements = WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.XPATH, XPATH_CHAPTER_ITEM))
        )
    except TimeoutException:
        logger.warning("当前页面未检测到章节链接")
        unique_chap = []
        logger.info(f"抓取完成，总有效章节：{len(unique_chap)} 个")
        return unique_chap
    current_page_chap = []
    print(f"\n【章节列表】")
    for idx, item in enumerate(chapter_elements):
        try:
            title = item.get_attribute("title").strip()
            href = item.get_attribute("href").strip()
            if title and href:
                current_page_chap.append({"title": title, "url": href})
                print(f"{idx+1}. {title}")
        except StaleElementReferenceException:
            continue
    logger.debug(f"检测到章节数量：{len(current_page_chap)}")
    all_chapters.extend(current_page_chap)
    # 全局去重
    unique_chap = []
    seen_url = set()
    for chap in all_chapters:
        if chap["url"] not in seen_url:
            seen_url.add(chap["url"])
            unique_chap.append(chap)
    logger.info(f"抓取完成，总有效章节：{len(unique_chap)} 个")
    return unique_chap
# ==================== 图片下载函数 ====================
def download_single_image(img_url, save_path, retry=3):
    for i in range(retry):
        try:
            resp = requests.get(img_url, headers=IMG_HEADERS, timeout=15, stream=True)
            if resp.status_code == 200:
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                logger.debug(f"图片保存成功：{save_path}")
                return True
            logger.warning(f"图片响应码{resp.status_code}，重试{i+1}/{retry}")
        except Exception as e:
            logger.warning(f"图片下载异常 {img_url} 重试{i+1}/{retry}：{str(e)}")
        random_delay(0.4, 0.8)
    logger.error(f"图片多次重试失败：{img_url}")
    return False
# ==================== 平滑滚动加载图片 ====================
def crawl_chapter_images(driver, chapter_info):
    chap_title = chapter_info["title"]
    chap_url = chapter_info["url"]
    safe_title = clean_folder_name(chap_title)
    chap_dir = os.path.join(SAVE_ROOT, safe_title)
    safe_mkdir(chap_dir)
    logger.info(f"\n===== 加载章节：{chap_title} =====")
    driver.get(chap_url)
    random_delay(3, 4)
    # 读取右上角页码标注
    total_page_num = 0
    try:
        page_text_elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "/html/body/div[1]/span[2]"))
        )
        page_text = page_text_elem.text.strip()
        logger.debug(f"读取页面右上角页码标注：{page_text}")
        if "/" in page_text:
            total_str = page_text.split("/")[-1]
            total_page_num = int(total_str)
        else:
            total_page_num = int(page_text)
        logger.info(f"该章节标准总页数：{total_page_num} 张")
    except Exception as e:
        logger.warning(f"读取右上角页码标注失败，无法获取标准总页数：{str(e)}")
    # 平滑小步滚动逻辑
    last_img_count = -1
    loop_times = 0
    max_loop = 20
    min_scroll_times = 3
    while loop_times < max_loop:
        driver.execute_script("window.scrollTo({top: 0, behavior: 'smooth'});")
        random_delay(0.4, 0.6)
        view_h = driver.execute_script("return window.innerHeight;")
        for step in range(1, 5):
            target_y = view_h * step
            driver.execute_script(f"window.scrollTo({{top: {target_y}, behavior: 'smooth'}});")
            random_delay(0.35, 0.55)
        driver.execute_script("window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'});")
        random_delay(1.2, 1.8)
        img_elements = driver.find_elements(By.CSS_SELECTOR, "img[data-src],img[data-original]")
        curr_count = len(img_elements)
        logger.debug(f"第{loop_times+1}次完整平滑滚动，当前检测图片数量：{curr_count}")
        exit_flag = False
        if total_page_num > 0 and curr_count >= total_page_num:
            logger.info(f"已抓取到标准总页数{total_page_num}张，停止滚动")
            exit_flag = True
        if curr_count == last_img_count and loop_times >= min_scroll_times:
            logger.debug(f"已完成最少{min_scroll_times}次滚动，无新增图片，停止滚动")
            exit_flag = True
        if exit_flag:
            break
        last_img_count = curr_count
        loop_times += 1
    # 过滤有效图片
    img_url_set = set()
    for img in img_elements:
        try:
            src = img.get_attribute("data-src") or img.get_attribute("data-original")
            if src and "loading" not in src and "ads" not in src:
                img_url_set.add(src)
        except StaleElementReferenceException:
            continue
    img_list = sorted(list(img_url_set))
    total_pic = len(img_list)
    logger.info(f"{chap_title} 共检测到 {total_pic} 张漫画图片（页面标注总页数：{total_page_num}）")
    # 批量下载图片
    for _, img_link in enumerate(img_list):
        suffix = img_link.split(".")[-1] if "." in img_link else "webp"
        save_name = f"{str(_+1).zfill(3)}.{suffix}"
        save_full_path = os.path.join(chap_dir, save_name)
        download_single_image(img_link, save_full_path)
        random_delay(0.1, 0.5)
    return total_pic
# ==================== 主程序 ====================
def main():
    safe_mkdir(SAVE_ROOT)
    driver = None
    try:
        driver = init_browser()
        all_chapters = get_all_chapter_list(driver)
        total_chap_num = len(all_chapters)
        if not all_chapters:
            logger.error("未抓取到任何章节，程序退出")
            return
        print(f"\n===== 全部章节共 {total_chap_num} 个 =====")
        print("支持输入格式示例：")
        print("1. 全部下载：直接回车")
        print("2. 单章下载：2")
        print("3. 分段下载：1-3,5,7-10")
        target_index_set = set()
        # 仅保留单次循环输入，删除多余前置input
        while True:
            range_input = input("请输入需要下载的章节范围：").strip()
            is_ok, idx_set = parse_range_input(range_input, total_chap_num)
            if is_ok:
                target_index_set = idx_set
                break
            print("输入格式错误或无有效章节，请重新输入！示例：1-5,8 或 2")
        target_chap_list = [all_chapters[i] for i in sorted(target_index_set)]
        download_count = len(target_chap_list)
        logger.info(f"筛选完成，即将批量下载 {download_count} 个章节")
        logger.info(f"\n========== 开始批量下载所选 {download_count} 个章节 ==========")
        for chap in target_chap_list:
            crawl_chapter_images(driver, chap)
        logger.success("\n==================== 所选章节全部下载完成 ====================")
    except Exception as e:
        logger.error(f"程序运行发生致命异常：{str(e)}", exc_info=True)
    finally:
        logger.info("任务流程结束，原有Edge窗口保留")
if __name__ == "__main__":
    main()
