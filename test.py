import requests
import json
import os
import time
import random
import gzip
import shutil
import tempfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# CONFIG
# ============================================================

CHANNELS_FILE = "channels.json"

JIOTVPLUS_FILE = "jiotvplus.json"

SOURCE_EPG_URLS = (
    "https://jioepg.djdoolky76.com/epg.xml.gz",
    "https://olidigital.space/olitv-epg.php",
    "https://whiplash.cc/scheds/schedule.xml",
)

CUSTOM_XMLTV_ENTRIES = (
    {
        "channel_id": "Music.Dummy",
        "channel_name": "24/7 Tamil Hits",
        "programme_channel": "tamil-hits",
        "title": "24/7 Tamil Hits",
        "description": "Non-stop Tamil hit songs, all day long.",
        "category": "Music",
    },
    {
        "channel_id": "24.7.Dummy",
        "channel_name": "24/7 Dummy Movies",
        "programme_channel": "dummy-movies",
        "title": "24/7 Non-Stop Movie Streaming",
        "description": (
            "Continuous round-the-clock movie broadcast featuring back-to-back "
            "cinematic blockbusters, action thrillers, and timeless classics all day long."
        ),
        "category": "Movie",
    },
    {
        "channel_id": "Sitcoms.Dummy",
        "channel_name": "24/7 Sitcoms",
        "programme_channel": "dummy-sitcoms",
        "title": "24/7 Non-Stop Sitcom Marathons",
        "description": (
            "Endless laughs with back-to-back comedy episodes, hilarious sitcom antics, "
            "and lighthearted fun all day long."
        ),
        "category": "Comedy",
    },
)

EPG_XML_GZ_FILE = "epg.xml.gz"


# ============================================================
# XML HELPERS
# ============================================================

def safe_xml(text):
    if text is None:
        return ""
    return xml_escape(str(text), {'"': "&quot;", "'": "&apos;"})


def normalize_channel_id(channel_id):
    """Return an XMLTV channel ID without JioTV's feed prefix."""
    if channel_id is None:
        return ""

    channel_id = str(channel_id)
    prefix = "jiotv."

    if channel_id.lower().startswith(prefix):
        return channel_id[len(prefix):]

    return channel_id


def format_xmltv_datetime(dt_str):
    if not dt_str:
        return ""
    clean_str = dt_str.replace("-", "").replace(":", "").replace("T", "").strip()
    if len(clean_str) == 14:
        return f"{clean_str} +0530"
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%Y%m%d%H%M%S +0530")
    except Exception:
        return ""



# ============================================================
# JIOTV EPG API
# ============================================================

EPG_API_URL = (
    "https://jiotvapi.cdn.jio.com/apis/v1.3/getepg/get"
    "?channel_id={channel_id}"
    "&offset={offset}"
)


# ============================================================
# HPROXY API
# ============================================================

HPROXY_URL = (
    "https://hproxy.com/api/proxy-list"
    "?format=json"
    "&country=IN"
    "&anonymity=anonymous"
    "&protocol=http,https"
)


# ============================================================
# PROXY TEST
# ============================================================

PROXY_TEST_CHANNEL = 2934

PROXY_TEST_OFFSET = 0


# ============================================================
# BATCH SETTINGS
# ============================================================

BATCH_SIZE = 50


# ============================================================
# RETRY SETTINGS
# ============================================================

MAX_RETRIES = 4

REQUEST_TIMEOUT = 30

PROXY_TEST_TIMEOUT = 10


# ============================================================
# OFFSETS
# ============================================================

OFFSETS = [
    -1,
    0,
    1,
    2
]


# ============================================================
# EPG IMAGE BASE URL
# ============================================================

EPG_IMAGE_URL = (
    "https://jiotvimages.cdn.jio.com/"
)


# ============================================================
# HEADERS
# ============================================================

HEADERS = {

    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64; "
        "rv:153.0) "
        "Gecko/20100101 Firefox/153.0"
    ),

    "Accept": (
        "application/json, "
        "text/plain, */*"
    ),

    "Accept-Language": (
        "en-US,en;q=0.5"
    ),

    "Referer": (
        "https://www.jiotv.com/"
    ),

    "Origin": (
        "https://www.jiotv.com"
    ),

    "Connection": "keep-alive",

    "Cache-Control": "no-cache"
}


# ============================================================
# GLOBAL WORKING PROXY
# ============================================================

WORKING_PROXY = None


# ============================================================
# LOAD CHANNELS.JSON
# ============================================================

def load_channels(channel_file=CHANNELS_FILE):

    if not os.path.exists(
        channel_file
    ):

        print(
            f"ERROR: {channel_file} "
            "not found."
        )

        return []


    try:

        with open(
            channel_file,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)


    except Exception as e:

        print(
            "ERROR reading channels.json:"
        )

        print(e)

        return []


    if not isinstance(
        data,
        list
    ):

        print(
            "ERROR: channels.json "
            "must contain a JSON array."
        )

        return []


    return data


# ============================================================
# EXTRACT EPG
# ============================================================

def extract_epg(data):

    if not isinstance(
        data,
        dict
    ):

        return []


    # --------------------------------------------------------
    # { "epg": [...] }
    # --------------------------------------------------------

    if isinstance(
        data.get("epg"),
        list
    ):

        return data["epg"]


    # --------------------------------------------------------
    # { "result": [...] }
    # --------------------------------------------------------

    if isinstance(
        data.get("result"),
        list
    ):

        return data["result"]


    # --------------------------------------------------------
    # { "data": [...] }
    # --------------------------------------------------------

    if isinstance(
        data.get("data"),
        list
    ):

        return data["data"]


    # --------------------------------------------------------
    # { "result": { "epg": [...] } }
    # --------------------------------------------------------

    result = data.get(
        "result"
    )


    if isinstance(
        result,
        dict
    ):

        if isinstance(
            result.get("epg"),
            list
        ):

            return result["epg"]


        if isinstance(
            result.get("data"),
            list
        ):

            return result["data"]


    return []


# ============================================================
# GET PROXIES FROM HPROXY API
# ============================================================

def get_hproxy_proxies():

    print()
    print(
        "=" * 70
    )

    print(
        "FETCHING INDIA PROXIES FROM HPROXY API"
    )

    print(
        "=" * 70
    )


    try:

        response = requests.get(

            HPROXY_URL,

            headers=HEADERS,

            timeout=30

        )

        response.raise_for_status()

        data = response.json()


    except Exception as e:

        print(
            "ERROR fetching HProxy API:"
        )

        print(e)

        return []


    if not isinstance(
        data,
        list
    ):

        print(
            "ERROR: HProxy API "
            "returned unexpected data."
        )

        return []


    proxies = []


    for item in data:

        if not isinstance(
            item,
            dict
        ):

            continue


        ip = item.get(
            "ip"
        )

        port = item.get(
            "port"
        )

        protocols = item.get(
            "protocols",
            []
        )

        status = item.get(
            "status"
        )


        if not ip or not port:

            continue


        # ----------------------------------------------------
        # Only currently alive proxies
        # ----------------------------------------------------

        if status != "alive":

            continue


        protocols = [

            str(protocol).lower()

            for protocol in protocols

        ]


        # ----------------------------------------------------
        # Only HTTP/HTTPS proxies
        # ----------------------------------------------------

        if (

            "http" not in protocols

            and

            "https" not in protocols

        ):

            continue


        proxy = f"{ip}:{port}"


        proxies.append({

            "proxy": proxy,

            "protocols": protocols,

            "latency_ms": item.get(
                "latency_ms"
            ),

            "uptime_24h": item.get(
                "uptime_24h"
            ),

            "uptime_7d": item.get(
                "uptime_7d"
            ),

            "uptime_pct": item.get(
                "uptime_pct"
            ),

            "reliability": item.get(
                "reliability"
            ),

            "verification_count": item.get(
                "verification_count"
            )

        })


    # --------------------------------------------------------
    # Remove duplicate proxies
    # --------------------------------------------------------

    unique = {}

    for item in proxies:

        unique[
            item["proxy"]
        ] = item


    proxies = list(
        unique.values()
    )


    # --------------------------------------------------------
    # Sort by latency
    # --------------------------------------------------------

    proxies.sort(

        key=lambda item: (

            item.get(
                "latency_ms"
            )

            if item.get(
                "latency_ms"
            ) is not None

            else 999999

        )

    )


    print(
        f"Found {len(proxies)} "
        "alive HTTP/HTTPS proxies."
    )


    print()


    for item in proxies:

        print(

            f"{item['proxy']} | "

            f"protocols="
            f"{','.join(item['protocols'])} | "

            f"latency="
            f"{item['latency_ms']}ms | "

            f"uptime24h="
            f"{item['uptime_24h']}% | "

            f"reliability="
            f"{item['reliability']}"

        )


    return proxies


# ============================================================
# TEST ONE PROXY AGAINST JIOTV
# ============================================================

def test_proxy(
    proxy_info
):

    proxy = proxy_info[
        "proxy"
    ]


    protocols = proxy_info.get(
        "protocols",
        []
    )


    test_url = EPG_API_URL.format(

        channel_id=PROXY_TEST_CHANNEL,

        offset=PROXY_TEST_OFFSET

    )


    # --------------------------------------------------------
    # HTTP proxy is used for both HTTP and HTTPS destinations.
    # Requests will establish CONNECT for HTTPS.
    # --------------------------------------------------------

    proxy_url = (
        f"http://{proxy}"
    )


    proxy_config = {

        "http": proxy_url,

        "https": proxy_url

    }


    print(
        f"Testing proxy: {proxy}"
    )


    try:

        response = requests.get(

            test_url,

            headers=HEADERS,

            proxies=proxy_config,

            timeout=PROXY_TEST_TIMEOUT

        )


        status = response.status_code


        print(

            f"  {proxy} -> "
            f"HTTP {status}"

        )


        if status != 200:

            return None


        try:

            data = response.json()

        except Exception:

            print(

                f"  {proxy} -> "
                "invalid JSON"

            )

            return None


        epg = extract_epg(
            data
        )


        if not epg:

            print(

                f"  {proxy} -> "
                "200 but no EPG data"

            )

            return None


        print()

        print(

            f"  [WORKING JIOTV PROXY] "
            f"{proxy}"

        )


        return proxy


    except requests.exceptions.ProxyError:

        print(
            f"  [PROXY ERROR] {proxy}"
        )


    except requests.exceptions.ConnectTimeout:

        print(
            f"  [CONNECT TIMEOUT] {proxy}"
        )


    except requests.exceptions.ReadTimeout:

        print(
            f"  [READ TIMEOUT] {proxy}"
        )


    except requests.exceptions.ConnectionError:

        print(
            f"  [CONNECTION ERROR] {proxy}"
        )


    except Exception as e:

        print(

            f"  [ERROR] "
            f"{proxy} - {e}"

        )


    return None


# ============================================================
# CHECK DIRECT CONNECTION
# ============================================================

def check_direct_connection():
    global WORKING_PROXY

    test_url = EPG_API_URL.format(
        channel_id=PROXY_TEST_CHANNEL,
        offset=PROXY_TEST_OFFSET
    )

    try:
        response = requests.get(
            test_url,
            headers=HEADERS,
            timeout=PROXY_TEST_TIMEOUT
        )

        if response.status_code == 200:
            data = response.json()
            if extract_epg(data):
                WORKING_PROXY = None
                return True

    except Exception:
        pass

    return False


# ============================================================
# FIND WORKING PROXY
# ============================================================

def find_working_proxy():

    global WORKING_PROXY


    proxy_list = get_hproxy_proxies()


    if not proxy_list:

        print(
            "No HProxy candidates found."
        )

        return None


    print()
    print(
        "=" * 70
    )

    print(
        "TESTING PROXIES AGAINST JIOTV EPG"
    )

    print(
        "=" * 70
    )


    max_proxy_workers = min(
        10,
        len(proxy_list)
    )


    with ThreadPoolExecutor(

        max_workers=max_proxy_workers

    ) as executor:


        futures = {

            executor.submit(

                test_proxy,

                proxy_info

            ): proxy_info

            for proxy_info in proxy_list

        }


        for future in as_completed(
            futures
        ):

            try:

                result = future.result()


                if result:

                    WORKING_PROXY = result


                    print()
                    print(
                        "=" * 70
                    )

                    print(
                        "WORKING PROXY FOUND"
                    )

                    print(
                        f"Proxy: "
                        f"{WORKING_PROXY}"
                    )

                    print(
                        "=" * 70
                    )


                    # ------------------------------------------------
                    # Cancel tests which have not started
                    # ------------------------------------------------

                    for pending in futures:

                        if not pending.done():

                            pending.cancel()


                    return WORKING_PROXY


            except Exception as e:

                print(
                    f"Proxy test error: {e}"
                )


    print()
    print(
        "=" * 70
    )

    print(
        "NO WORKING JIOTV PROXY FOUND"
    )

    print(
        "=" * 70
    )


    return None


# ============================================================
# CREATE SESSION
# ============================================================

def create_session():

    session = requests.Session()


    session.headers.update(
        HEADERS
    )


    if WORKING_PROXY:

        proxy_url = (
            f"http://{WORKING_PROXY}"
        )


        session.proxies.update({

            "http": proxy_url,

            "https": proxy_url

        })


    return session


# ============================================================
# THUMBNAIL URL
# ============================================================

def get_thumbnail_url(
    path
):

    if not path:

        return None


    if (

        path.startswith(
            "http://"
        )

        or

        path.startswith(
            "https://"
        )

    ):

        return path


    path = path.lstrip(
        "/"
    )


    return (
        EPG_IMAGE_URL
        +
        path
    )


# ============================================================
# SERVER DATE
# ============================================================

def get_server_date(
    server_date
):

    if not server_date:

        return None


    try:

        dt = datetime.fromisoformat(
            server_date
        )


        return dt.strftime(
            "%Y-%m-%d"
        )


    except Exception:

        return server_date.split(
            "T"
        )[0]


# ============================================================
# CREATE DATETIME
# ============================================================

def create_datetime(

    server_date,

    time_string

):

    if (

        not server_date

        or

        not time_string

    ):

        return None


    try:

        # ----------------------------------------------------
        # Handle HH:MM
        # ----------------------------------------------------

        if len(
            time_string
        ) == 5:

            time_part = datetime.strptime(

                time_string,

                "%H:%M"

            ).time()


        else:

            time_part = datetime.strptime(

                time_string,

                "%H:%M:%S"

            ).time()


        date_part = datetime.strptime(

            server_date,

            "%Y-%m-%d"

        ).date()


        result = datetime.combine(

            date_part,

            time_part

        )


        return result.strftime(

            "%Y-%m-%dT%H:%M:%S"

        )


    except Exception:

        return None


# ============================================================
# PROCESS PROGRAM
# ============================================================

def process_program(

    program,

    offset_server_date

):

    showtime = program.get(
        "showtime"
    )


    endtime = program.get(
        "endtime"
    )


    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Every program belonging to this offset gets
    # the SAME server date.
    # --------------------------------------------------------

    server_date = (
        offset_server_date
    )


    start_date = create_datetime(

        server_date,

        showtime

    )


    end_date = create_datetime(

        server_date,

        endtime

    )


    # --------------------------------------------------------
    # If program crosses midnight
    # --------------------------------------------------------

    if (

        start_date

        and

        end_date

        and

        end_date < start_date

    ):

        try:

            end_dt = datetime.strptime(

                end_date,

                "%Y-%m-%dT%H:%M:%S"

            )


            end_dt += timedelta(
                days=1
            )


            end_date = end_dt.strftime(

                "%Y-%m-%dT%H:%M:%S"

            )


        except Exception:

            pass


    # --------------------------------------------------------
    # Thumbnail
    # --------------------------------------------------------

    thumbnail = (

        program.get(
            "episodeThumbnail"
        )

        or

        program.get(
            "episodePoster"
        )

        or

        program.get(
            "thumbnail"
        )

        or

        program.get(
            "thumbnailUrl"
        )

    )


    thumbnail_url = (
        get_thumbnail_url(
            thumbnail
        )
    )


    # --------------------------------------------------------
    # Program JSON
    # --------------------------------------------------------

    return {

        "serverDate": server_date,

        "showName": program.get(
            "showname"
        ),

        "description": program.get(
            "description"
        ),

        "startDate": start_date,

        "endDate": end_date,

        "showTime": showtime,

        "endTime": endtime,

        "showCategory": program.get(
            "showCategory"
        ),

        "thumbnailUrl": thumbnail_url

    }


# ============================================================
# GET EPG WITH RETRIES
# ============================================================

def get_epg(

    session,

    channel_id,

    offset

):

    url = EPG_API_URL.format(

        channel_id=channel_id,

        offset=offset

    )


    for attempt in range(

        1,

        MAX_RETRIES + 1

    ):

        try:

            response = session.get(

                url,

                timeout=REQUEST_TIMEOUT

            )


            status = response.status_code


            # =================================================
            # HTTP 450
            # =================================================

            if status == 450:

                wait_time = (

                    3 * (

                        2 ** (

                            attempt - 1

                        )

                    )

                    +

                    random.uniform(

                        0.5,

                        2.5

                    )

                )


                if attempt < MAX_RETRIES:

                    print(

                        f"      Channel "
                        f"{channel_id} "
                        f"Offset {offset}: "
                        f"HTTP 450 - "
                        f"retrying in "
                        f"{wait_time:.1f}s"

                    )


                    time.sleep(
                        wait_time
                    )


                    continue


                print(

                    f"      Channel "
                    f"{channel_id} "
                    f"Offset {offset}: "
                    f"HTTP 450 after "
                    f"{MAX_RETRIES} attempts"

                )


                return []


            # =================================================
            # HTTP 429
            # =================================================

            if status == 429:

                retry_after = (
                    response.headers.get(
                        "Retry-After"
                    )
                )


                if retry_after:

                    try:

                        wait_time = float(
                            retry_after
                        )

                    except ValueError:

                        wait_time = 10

                else:

                    wait_time = (

                        5 * (

                            2 ** (

                                attempt - 1

                            )

                        )

                        +

                        random.uniform(

                            1,

                            3

                        )

                    )


                if attempt < MAX_RETRIES:

                    print(

                        f"      Channel "
                        f"{channel_id} "
                        f"Offset {offset}: "
                        f"HTTP 429 - "
                        f"waiting "
                        f"{wait_time:.1f}s"

                    )


                    time.sleep(
                        wait_time
                    )


                    continue


                print(

                    f"      Channel "
                    f"{channel_id} "
                    f"Offset {offset}: "
                    f"HTTP 429 after "
                    f"{MAX_RETRIES} attempts"

                )


                return []


            # =================================================
            # OTHER HTTP ERRORS
            # =================================================

            response.raise_for_status()


            # =================================================
            # JSON
            # =================================================

            data = response.json()


            return extract_epg(
                data
            )


        # =====================================================
        # CONNECTION / TIMEOUT
        # =====================================================

        except (

            requests.exceptions.ConnectionError,

            requests.exceptions.Timeout

        ) as e:


            if attempt < MAX_RETRIES:

                wait_time = (

                    2 ** attempt

                    +

                    random.uniform(

                        0.5,

                        2

                    )

                )


                print(

                    f"      Channel "
                    f"{channel_id} "
                    f"Offset {offset}: "
                    f"connection error - "
                    f"retrying in "
                    f"{wait_time:.1f}s"

                )


                time.sleep(
                    wait_time
                )


                continue


            print(

                f"      Channel "
                f"{channel_id} "
                f"Offset {offset} "
                f"ERROR: {e}"

            )


            return []


        # =====================================================
        # INVALID JSON
        # =====================================================

        except requests.exceptions.JSONDecodeError:

            print(

                f"      Channel "
                f"{channel_id} "
                f"Offset {offset}: "
                f"Invalid JSON"

            )


            return []


        # =====================================================
        # OTHER REQUEST ERROR
        # =====================================================

        except requests.exceptions.RequestException as e:

            print(

                f"      Channel "
                f"{channel_id} "
                f"Offset {offset} "
                f"ERROR: {e}"

            )


            return []


        except Exception as e:

            print(

                f"      Channel "
                f"{channel_id} "
                f"Offset {offset} "
                f"ERROR: {e}"

            )


            return []


    return []


# ============================================================
# PROCESS ONE CHANNEL
# ============================================================

def process_channel(
    channel
):

    # --------------------------------------------------------
    # Channel information
    # --------------------------------------------------------

    channel_id = channel.get(
        "channel_id"
    )

    channel_name = channel.get(
        "channel_name"
    )

    category = channel.get(
        "category"
    )

    logo_url = (
        channel.get("logo_url")
        or
        channel.get("logoUrl")
    )


    if channel_id is None:

        return (

            False,

            None,

            "Missing channel_id",

            None

        )


    # --------------------------------------------------------
    # Create session using working proxy
    # --------------------------------------------------------

    session = create_session()


    all_programs = []


    # ========================================================
    # PROCESS OFFSETS
    # ========================================================

    for offset in OFFSETS:

        epg_data = get_epg(

            session,

            channel_id,

            offset

        )


        if not epg_data:

            continue


        # ----------------------------------------------------
        # Get server date for this offset
        # ----------------------------------------------------

        offset_server_date = None


        for program in epg_data:

            raw_server_date = (

                program.get(
                    "serverDate"
                )

            )


            if raw_server_date:

                offset_server_date = (

                    get_server_date(

                        raw_server_date

                    )

                )


                break


        if not offset_server_date:

            continue


        print(

            f"Channel {channel_id} | "
            f"Offset {offset} | "
            f"Date {offset_server_date} | "
            f"Programs {len(epg_data)}"

        )


        # ----------------------------------------------------
        # Process all programs
        # ----------------------------------------------------

        for program in epg_data:

            program_channel_id = (

                program.get(
                    "channel_id"
                )

            )


            # ------------------------------------------------
            # Ignore another channel if API returns one
            # ------------------------------------------------

            if (

                program_channel_id is not None

                and

                str(
                    program_channel_id
                )

                !=

                str(
                    channel_id
                )

            ):

                continue


            processed = process_program(

                program,

                offset_server_date

            )


            all_programs.append(
                processed
            )


    # ========================================================
    # REMOVE DUPLICATES
    # ========================================================

    unique_programs = {}


    for program in all_programs:

        key = (

            program.get(
                "serverDate"
            ),

            program.get(
                "showTime"
            ),

            program.get(
                "endTime"
            ),

            program.get(
                "showName"
            )

        )


        unique_programs[key] = (
            program
        )


    all_programs = list(
        unique_programs.values()
    )


    # ========================================================
    # SORT PROGRAMS
    # ========================================================

    all_programs.sort(

        key=lambda item: (

            item.get(
                "startDate"
            )

            or

            ""

        )

    )


    # ========================================================
    # FINAL CHANNEL DATA
    # ========================================================

    channel_output = {

        "channel_id": channel_id,

        "channel_name": channel_name,

        "category": category,

        "logo_url": logo_url,

        "programs": all_programs

    }

    return (

        True,

        channel_id,

        len(all_programs),

        channel_output

    )


# ============================================================
# PROCESS 50 CHANNELS
# ============================================================

def process_batch(

    batch,

    batch_number,

    total_batches

):

    print()
    print(
        "=" * 70
    )

    print(

        f"BATCH "
        f"{batch_number}/"
        f"{total_batches}"

    )

    print(

        f"Channels: "
        f"{len(batch)}"

    )

    print(

        f"Proxy: "
        f"{WORKING_PROXY}"

    )

    print(
        "=" * 70
    )


    completed = 0

    failed = 0

    batch_channels = []


    # --------------------------------------------------------
    # 50 CHANNELS CONCURRENTLY
    # --------------------------------------------------------

    with ThreadPoolExecutor(

        max_workers=BATCH_SIZE

    ) as executor:


        futures = {

            executor.submit(

                process_channel,

                channel

            ): channel

            for channel in batch

        }


        for future in as_completed(
            futures
        ):

            channel = futures[
                future
            ]


            channel_id = channel.get(
                "channel_id"
            )


            channel_name = channel.get(
                "channel_name"
            )


            try:

                success, result_id, result, channel_data = (

                    future.result()

                )


                if success:

                    completed += 1

                    if channel_data:
                        batch_channels.append(channel_data)


                    print(

                        f"[OK] "
                        f"{result_id} - "
                        f"{channel_name} - "
                        f"{result} programs"

                    )


                else:

                    failed += 1


                    print(

                        f"[FAILED] "
                        f"{channel_id} - "
                        f"{channel_name} - "
                        f"{result}"

                    )


            except Exception as e:

                failed += 1


                print(

                    f"[FAILED] "
                    f"{channel_id} - "
                    f"{channel_name} - "
                    f"{e}"

                )


    print()
    print(

        f"Batch {batch_number} "
        f"completed"

    )

    print(
        f"Successful: {completed}"
    )

    print(
        f"Failed: {failed}"
    )

    return batch_channels


# ============================================================
# LOAD ALL CHANNEL DATA
# ============================================================

def load_all_channel_data(channels_meta, in_memory_channels=None):
    """
    Consolidates channel EPG data preserving channels.json order.
    """
    channels_dict = {}

    if in_memory_channels:
        for ch in in_memory_channels:
            cid = str(ch.get("channel_id"))
            channels_dict[cid] = ch

    final_channels = []

    for ch_meta in channels_meta:
        cid = str(ch_meta.get("channel_id"))

        if cid in channels_dict:
            final_channels.append(channels_dict[cid])
        else:
            final_channels.append({
                "channel_id": ch_meta.get("channel_id"),
                "channel_name": ch_meta.get("channel_name"),
                "category": ch_meta.get("category"),
                "logo_url": ch_meta.get("logo_url") or ch_meta.get("logoUrl"),
                "programs": []
            })

    return final_channels


# ============================================================
# GENERATE XMLTV GUIDE AND GZIP COMPRESSED XMLTV
# ============================================================

def generate_xmltv(channels_data, xml_file, gz_file):
    print()
    print("=" * 70)
    print("GENERATING XMLTV EPG (XML & XML.GZ)")
    print("=" * 70)

    total_programs = 0

    try:
        with open(xml_file, "w", encoding="utf-8") as file:
            file.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            file.write('<tv generator-info-name="jiotv-epg" source-info-name="JioTV">\n')

            # ----------------------------------------------------
            # 1. Channel entries
            # ----------------------------------------------------
            for ch in channels_data:
                ch_id = safe_xml(normalize_channel_id(ch.get("channel_id")))
                ch_name = safe_xml(ch.get("channel_name"))
                logo = safe_xml(ch.get("logo_url") or ch.get("logoUrl"))

                file.write(f'  <channel id="{ch_id}">\n')
                file.write(f'    <display-name lang="en">{ch_name}</display-name>\n')
                if logo:
                    file.write(f'    <icon src="{logo}" />\n')
                file.write('  </channel>\n')

            # ----------------------------------------------------
            # 2. Programme entries
            # ----------------------------------------------------
            for ch in channels_data:
                ch_id = safe_xml(normalize_channel_id(ch.get("channel_id")))
                programs = ch.get("programs", [])

                for prog in programs:
                    start = format_xmltv_datetime(prog.get("startDate"))
                    stop = format_xmltv_datetime(prog.get("endDate"))

                    if not start or not stop:
                        continue

                    title = safe_xml(prog.get("showName") or ch.get("channel_name") or "No Information")
                    desc = safe_xml(prog.get("description"))
                    category = safe_xml(prog.get("showCategory") or ch.get("category"))
                    thumb = safe_xml(prog.get("thumbnailUrl"))

                    file.write(f'  <programme start="{start}" stop="{stop}" channel="{ch_id}">\n')
                    file.write(f'    <title lang="en">{title}</title>\n')

                    if desc:
                        file.write(f'    <desc lang="en">{desc}</desc>\n')

                    if category:
                        file.write(f'    <category lang="en">{category}</category>\n')

                    if thumb:
                        file.write(f'    <icon src="{thumb}" />\n')

                    file.write('  </programme>\n')
                    total_programs += 1

            file.write('</tv>\n')

        # --------------------------------------------------------
        # 3. Gzip compression
        # --------------------------------------------------------
        with open(xml_file, "rb") as f_in:
            with gzip.open(gz_file, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        xml_size_mb = os.path.getsize(xml_file) / (1024 * 1024)
        gz_size_mb = os.path.getsize(gz_file) / (1024 * 1024)

        print(f"Channels written: {len(channels_data)}")
        print(f"Programmes written: {total_programs}")
        print(f"Generated XML: {xml_file} ({xml_size_mb:.2f} MB)")
        print(f"Generated GZ:  {gz_file} ({gz_size_mb:.2f} MB)")

    except Exception as e:
        print(f"ERROR generating XMLTV EPG: {e}")


def xmltv_tag_name(element):
    """Return an XML tag name without an optional namespace."""
    return element.tag.rsplit("}", 1)[-1]


def download_source_epg(url):
    """Download and parse one XMLTV guide, compressed or uncompressed."""
    print(f"Downloading source EPG: {url}")

    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    try:
        xml_data = gzip.decompress(response.content)
    except OSError:
        # Also support servers that transparently return an already-decoded file.
        xml_data = response.content

    return ET.ElementTree(ET.fromstring(xml_data))


def normalize_xmltv_channel_ids(root):
    """Change XMLTV IDs such as jiotv.832 to 832 in-place."""
    for element in root:
        tag = xmltv_tag_name(element)

        if tag == "channel" and "id" in element.attrib:
            element.set("id", normalize_channel_id(element.get("id")))
        elif tag == "programme" and "channel" in element.attrib:
            element.set("channel", normalize_channel_id(element.get("channel")))


def append_custom_epg_entries(root):
    """Add the user-supplied always-on channels, replacing previous copies."""
    custom_channel_ids = {entry["channel_id"] for entry in CUSTOM_XMLTV_ENTRIES}
    custom_programme_channels = {
        entry["programme_channel"] for entry in CUSTOM_XMLTV_ENTRIES
    }

    for element in list(root):
        tag = xmltv_tag_name(element)

        if (
            tag == "channel"
            and element.get("id") in custom_channel_ids
        ) or (
            tag == "programme"
            and element.get("channel") in custom_programme_channels
        ):
            root.remove(element)

    for entry in CUSTOM_XMLTV_ENTRIES:
        channel = ET.SubElement(root, "channel", id=entry["channel_id"])
        ET.SubElement(channel, "display-name").text = entry["channel_name"]

        programme = ET.SubElement(
            root,
            "programme",
            start="20261012000000 +0530",
            stop="20261013000000 +0530",
            channel=entry["programme_channel"],
        )
        ET.SubElement(programme, "title", lang="en").text = entry["title"]
        ET.SubElement(programme, "desc", lang="en").text = entry["description"]
        ET.SubElement(programme, "category", lang="en").text = entry["category"]


def merge_epg_guides(refreshed_xml, channel_ids, gz_file=EPG_XML_GZ_FILE):
    """Merge all source guides and write only the compressed XMLTV output."""
    base_tree = None

    for source_url in SOURCE_EPG_URLS:
        source_tree = download_source_epg(source_url)
        source_root = source_tree.getroot()
        normalize_xmltv_channel_ids(source_root)

        if base_tree is None:
            base_tree = source_tree
            continue

        base_root = base_tree.getroot()
        for element in source_root:
            if xmltv_tag_name(element) in {"channel", "programme"}:
                base_root.append(element)

    if base_tree is None:
        raise RuntimeError("No source EPG guides were downloaded.")

    base_root = base_tree.getroot()
    refreshed_root = ET.parse(refreshed_xml).getroot()

    normalize_xmltv_channel_ids(refreshed_root)

    refreshed_ids = {
        normalize_channel_id(channel_id)
        for channel_id in channel_ids
        if channel_id is not None
    }

    # Replace the downloaded entries for requested channels so programmes do not
    # remain duplicated or stale after the API data is appended.
    for element in list(base_root):
        tag = xmltv_tag_name(element)
        element_id = (
            element.get("id")
            if tag == "channel"
            else element.get("channel")
            if tag == "programme"
            else None
        )

        if element_id in refreshed_ids:
            base_root.remove(element)

    for element in refreshed_root:
        if xmltv_tag_name(element) in {"channel", "programme"}:
            base_root.append(element)

    append_custom_epg_entries(base_root)

    ET.indent(base_tree, space="  ")

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as temp_file:
        temp_xml = temp_file.name

    try:
        base_tree.write(temp_xml, encoding="utf-8", xml_declaration=True)

        with open(temp_xml, "rb") as f_in:
            with gzip.open(gz_file, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
    finally:
        if os.path.exists(temp_xml):
            os.unlink(temp_xml)

    print(f"Merged API EPG for {len(refreshed_ids)} channels")
    print(f"Generated GZ:  {gz_file}")


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "=" * 70
    )

    print(
        "JIO TV EPG CHANNEL GENERATOR"
    )

    print(
        "=" * 70
    )


    # ========================================================
    # STEP 1
    # CHECK DIRECT ACCESS / FIND WORKING INDIA PROXY
    # ========================================================

    print("Checking direct connection to JioTV API...")

    if check_direct_connection():
        print("Direct connection to JioTV API successful! No proxy needed.")
        working_proxy = "Direct (No Proxy)"
    else:
        print("Direct connection not available. Searching for working India proxy...")
        working_proxy = (
            find_working_proxy()
        )

        if not working_proxy:

            print()
            print(
                "STOPPING."
            )

            print(
                "No working India proxy "
                "could access JioTV EPG."
            )

            return


    # ========================================================
    # STEP 2
    # LOAD CHANNELS
    # ========================================================

    channels = load_channels(JIOTVPLUS_FILE)


    if not channels:

        print(
            "No channels found."
        )

        return


    print()
    print(
        f"Total channels: "
        f"{len(channels)}"
    )

    print(
        f"Channels per batch: "
        f"{BATCH_SIZE}"
    )

    print(
        f"Offsets: "
        f"{OFFSETS}"
    )

    print(
        f"Working proxy: "
        f"{working_proxy}"
    )


    # ========================================================
    # STEP 3
    # SPLIT INTO BATCHES
    # ========================================================

    batches = [

        channels[
            i:i + BATCH_SIZE
        ]

        for i in range(

            0,

            len(channels),

            BATCH_SIZE

        )

    ]


    total_batches = len(
        batches
    )


    print()
    print(
        f"Total batches: "
        f"{total_batches}"
    )


    # ========================================================
    # STEP 4
    # PROCESS BATCHES
    # ========================================================

    all_collected_channels = []

    for index, batch in enumerate(

        batches,

        start=1

    ):

        batch_channels = process_batch(

            batch,

            index,

            total_batches

        )

        all_collected_channels.extend(batch_channels)


    # ========================================================
    # STEP 5
    # GENERATE THE REFRESHED JIOTVPLUS GUIDE, THEN MERGE IT INTO
    # THE DOWNLOADED FULL GUIDE.
    # ========================================================

    all_channels_data = load_all_channel_data(
        channels,
        all_collected_channels
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        refreshed_xml = os.path.join(temp_dir, "jiotvplus.xml")
        refreshed_gz = os.path.join(temp_dir, "jiotvplus.xml.gz")

        generate_xmltv(
            all_channels_data,
            refreshed_xml,
            refreshed_gz
        )

        merge_epg_guides(
            refreshed_xml,
            [channel.get("channel_id") for channel in channels],
            EPG_XML_GZ_FILE
        )


    # ========================================================
    # DONE
    # ========================================================

    print()
    print(
        "=" * 70
    )

    print(
        "ALL CHANNELS COMPLETED"
    )

    print(
        f"Proxy used: "
        f"{WORKING_PROXY}"
    )

    print(
        f"Output GZ: "
        f"{EPG_XML_GZ_FILE}"
    )

    print(
        "=" * 70
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
