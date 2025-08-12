
def download_largest_google_image(query):
    import os
    import requests
    from selenium import webdriver
    from bs4 import BeautifulSoup
    import time
    import urllib.parse

    temp_dir = "./imag_temp"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    driver = webdriver.Chrome()
    encoded_query = urllib.parse.quote(query)
    driver.get(f"https://www.google.com/search?tbm=isch&q={encoded_query}")

    time.sleep(0.5)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    images = soup.find_all("img")
    img_urls = []
    for img in images:
        img_url = img.get("src") or img.get("data-src")
        if img_url and img_url.startswith("http"):
            img_urls.append(img_url)
        if len(img_urls) >= 25:
            break

    largest_size = 0
    largest_path = None
    largest_ext = "jpg"
    extension_map = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/gif": "gif"
    }

    for i, img_url in enumerate(img_urls):
        try:
            response = requests.get(img_url, stream=True, timeout=10)
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "").lower()
                if "image" in content_type:
                    file_extension = extension_map.get(content_type, "jpg")
                    file_path = os.path.join(temp_dir, f"image_{i}.{file_extension}")
                    with open(file_path, "wb") as f:
                        for chunk in response.iter_content(1024):
                            f.write(chunk)
                    file_size = os.path.getsize(file_path)
                    if file_size > largest_size:
                        largest_size = file_size
                        largest_path = file_path
                        largest_ext = file_extension
                # else: skip non-image
        except Exception:
            pass

    # Save the largest image to ./imag/largest_image.{ext}
    if largest_path:
        final_dir = "./imag"
        if not os.path.exists(final_dir):
            os.makedirs(final_dir)
        final_path = os.path.join(final_dir, f"largest_image.{largest_ext}")
        with open(largest_path, "rb") as src, open(final_path, "wb") as dst:
            dst.write(src.read())
        print(f"Saved largest image: {final_path} ({largest_size} bytes)")
    else:
        print("No valid images found.")

    # Clean up temp files
    for fname in os.listdir(temp_dir):
        try:
            os.remove(os.path.join(temp_dir, fname))
        except Exception:
            pass
    os.rmdir(temp_dir)

if __name__ == "__main__":
    download_largest_google_image("Depression-era agricultural landscape, 1933, Dust Bowl farms")

print("Image download completed!")