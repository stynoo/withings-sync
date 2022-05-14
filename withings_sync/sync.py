"""This module syncs measurement data from Withings to Garmin a/o TrainerRoad."""
import argparse
import csv
import time
import sys
import os
import logging
import json

from datetime import date, datetime

from withings_sync.withings2 import WithingsAccount
from withings_sync.garmin import GarminConnect
from withings_sync.trainerroad import TrainerRoad
from withings_sync.fit import FitEncoder_Weight


try:
    with open("/run/secrets/garmin_username", encoding="utf-8") as secret:
        GARMIN_USERNAME = secret.read()
except OSError:
    GARMIN_USERNAME = ""

try:
    with open("/run/secrets/garmin_password", encoding="utf-8") as secret:
        GARMIN_PASSWORD = secret.read()
except OSError:
    GARMIN_PASSWORD = ""

if "GC_USERNAME" in os.environ:
    GARMIN_USERNAME = os.getenv("GARMIN_USERNAME")

if "GC_PASSWORD" in os.environ:
    GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")


try:
    with open("/run/secrets/trainerroad_username", encoding="utf-8") as secret:
        TRAINERROAD_USERNAME = secret.read()
except OSError:
    TRAINERROAD_USERNAME = ""

try:
    with open("/run/secrets/trainerroad_password", encoding="utf-8") as secret:
        TRAINERROAD_PASSWORD = secret.read()
except OSError:
    TRAINERROAD_PASSWORD = ""

if "TR_USERNAME" in os.environ:
    TRAINERROAD_USERNAME = os.getenv("TRAINERROAD_USERNAME")

if "TR_PASSWORD" in os.environ:
    TRAINERROAD_PASSWORD = os.getenv("TRAINERROAD_PASSWORD")


def get_args():
    """get command-line arguments"""
    parser = argparse.ArgumentParser(
        description=(
            "A tool for synchronisation of Withings "
            "(ex. Nokia Health Body) to Garmin Connect"
            " and Trainer Road or to provide a json string."
        )
    )

    def date_parser(date_string):
        return datetime.strptime(date_string, "%Y-%m-%d")

    parser.add_argument(
        "--garmin-username",
        "--gu",
        default=GARMIN_USERNAME,
        type=str,
        metavar="GARMIN_USERNAME",
        help="username to log in to Garmin Connect.",
    )
    parser.add_argument(
        "--garmin-password",
        "--gp",
        default=GARMIN_PASSWORD,
        type=str,
        metavar="GARMIN_PASSWORD",
        help="password to log in to Garmin Connect.",
    )

    parser.add_argument(
        "--trainerroad-username",
        "--tu",
        default=TRAINERROAD_USERNAME,
        type=str,
        metavar="TRAINERROAD_USERNAME",
        help="username to log in to TrainerRoad.",
    )
    parser.add_argument(
        "--trainerroad-password",
        "--tp",
        default=TRAINERROAD_PASSWORD,
        type=str,
        metavar="TRAINERROAD_PASSWORD",
        help="password to log in to TrainerRoad.",
    )

    parser.add_argument("--fromdate", "-f", type=date_parser, metavar="DATE")
    parser.add_argument(
        "--todate", "-t", type=date_parser, default=date.today(), metavar="DATE"
    )

    parser.add_argument(
        "--to-fit", "-F", action="store_true", help=("Write output file in FIT format.")
    )
    parser.add_argument(
        "--to-json",
        "-J",
        action="store_true",
        help=("Write output file in JSON format."),
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        metavar="BASENAME",
        help=("Write downloaded measurements to file."),
    )

    parser.add_argument(
        "--no-upload",
        action="store_true",
        help=("Won't upload to Garmin Connect or " "TrainerRoad."),
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Run verbosely")

    return parser.parse_args()


def sync_garmin(fit_file):
    """Sync generated fit file to Garmin Connect"""
    garmin = GarminConnect()
    session = garmin.login(ARGS.garmin_username, ARGS.garmin_password)
    return garmin.upload_file(fit_file.getvalue(), session)


def sync_trainerroad(last_weight):
    """Sync measured weight to TrainerRoad"""
    t_road = TrainerRoad(ARGS.trainerroad_username, ARGS.trainerroad_password)
    t_road.connect()
    logging.info("Current TrainerRoad weight: %s kg ", t_road.weight)
    logging.info("Updating TrainerRoad weight to %s kg", last_weight)
    t_road.weight = round(last_weight, 1)
    t_road.disconnect()
    return t_road.weight


def generate_fitdata(syncdata):
    """Generate fit data from measured data"""
    logging.debug("Generating fit data...")

    fit = FitEncoder_Weight()
    fit.write_file_info()
    fit.write_file_creator()

    for record in syncdata:
        fit.write_device_info(timestamp=record["date_time"])
        fit.write_weight_scale(
            timestamp=record["date_time"],
            weight=record["weight"],
            percent_fat=record["fat_ratio"],
            percent_hydration=record["percent_hydration"],
            bone_mass=record["bone_mass"],
            muscle_mass=record["muscle_mass"],
            bmi=record["bmi"],
        )

    fit.finish()

    logging.debug("Fit data generated...")
    return fit


def generate_jsondata(syncdata):
    """Generate fit data from measured data"""
    logging.debug("Generating json data...")

    json_data = {}
    for record in syncdata:
        json_data[str(record["date_time"])] = {
            "unit": "kg",
            "weight": record["weight"],
            "fat_ratio": record["fat_ratio"],
            "muscle_mass": record["muscle_mass"],
            "hydration_ratio": record["hydration"],
            "bone_mass": record["bone_mass"],
            "bmi": record["bmi"],
        }
    logging.debug("Json data generated...")
    return json_data


def generate_csvdata(syncdata):
    """Generate csv data from measured data"""
    logging.debug("Generating csv data...")

    csv_data = []
    for record in syncdata:
        record_data = [
            str(record["date_time"]),
            record["weight"],
            record["bmi"],
            record["fat_ratio"],
            record["bone_mass"],
            record["percent_hydration"],
            record["muscle_mass"],
        ]
        csv_data.append(record_data)
    return csv_data


def prepare_syncdata(height, groups):
    """Prepare measurement data to be sent"""
    syncdata = []

    last_date_time = None
    last_weight = None

    for group in groups:
        # Get extra physical measurements
        groupdata = {
            "date_time": group.get_datetime(),
            "height": height,
            "weight": group.get_weight(),
            "fat_ratio": group.get_fat_ratio(),
            "muscle_mass": group.get_muscle_mass(),
            "hydration": group.get_hydration(),
            "percent_hydration": None,
            "bone_mass": group.get_bone_mass(),
            "bmi": None,
        }
        raw_data = group.get_raw_data()

        if groupdata["weight"] is None:
            logging.info(
                "This Withings metric contains no weight data.  Not syncing..."
            )
            logging.debug("Detected data: ")
            for dataentry in raw_data:
                logging.debug(dataentry)
            continue
        if height:
            groupdata["bmi"] = round(
                groupdata["weight"] / pow(groupdata["height"], 2), 1
            )
        if groupdata["hydration"]:
            groupdata["percent_hydration"] = round(
                groupdata["hydration"] * 100.0 / groupdata["weight"], 2
            )

        logging.debug(
            "Record: %s, height=%s m, "
            "weight=%s kg, "
            "fat_ratio=%s %%, "
            "muscle_mass=%s kg, "
            "percent_hydration=%s %%, "
            "bone_mass=%s kg, "
            "bmi=%s",
            groupdata["date_time"],
            groupdata["height"],
            groupdata["weight"],
            groupdata["fat_ratio"],
            groupdata["muscle_mass"],
            groupdata["percent_hydration"],
            groupdata["bone_mass"],
            groupdata["bmi"],
        )
        if last_date_time is None or groupdata["date_time"] > last_date_time:
            last_date_time = groupdata["date_time"]
            last_weight = groupdata["weight"]

        try:
            with open(CSV_FILENAME, "r", newline="", encoding="utf-8") as csvfile:
                reader = csvfile.read()
                if str(groupdata["date_time"]) not in reader:
                    logging.debug(
                        "Record for %s not found in csv file... adding...",
                        groupdata["date_time"],
                    )
                    syncdata.append(groupdata)
                else:
                    logging.debug(
                        "Record for %s found in csv file... skipping...",
                        groupdata["date_time"],
                    )
        except FileNotFoundError:
            logging.debug(
                "%s: file not found... adding record for %s ...",
                CSV_FILENAME,
                groupdata["date_time"],
            )
            syncdata.append(groupdata)

    return last_weight, last_date_time, syncdata


def write_to_file_when_needed(fit_data, json_data, csv_data):
    """Write measurements to file when requested"""
    if ARGS.to_fit:
        logging.info("Writing fitfile to %s.", FIT_FILENAME)
        try:
            with open(FIT_FILENAME, "wb") as fitfile:
                fitfile.write(fit_data.getvalue())
        except OSError:
            logging.error("Unable to open output fitfile!")
    if ARGS.to_json:
        logging.info("Writing jsonfile to %s.", JSON_FILENAME)
        try:
            with open(JSON_FILENAME, "w", encoding="utf-8") as jsonfile:
                json.dump(json_data, jsonfile, indent=4)
        except OSError:
            logging.error("Unable to open output jsonfile!")

    # We always write a csv file: used to avoid dupes in Garmin Connect
    try:
        with open(CSV_FILENAME, "r+", newline="", encoding="utf-8") as csvfile:
            csvfile.close()
    except FileNotFoundError:
        logging.debug("%s: csv file not found... creating...", CSV_FILENAME)
        with open(CSV_FILENAME, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Body"])
            writer.writerow(
                ["Date", "Weight", "BMI", "Fat", "Bone", "Hydration", "Muscle"]
            )
    else:
        logging.debug("%s: csv file found...  appending...", CSV_FILENAME)
    finally:
        with open(CSV_FILENAME, "a", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            for csv_record in csv_data:
                writer.writerow(csv_record)


def sync():
    """Sync measurements from Withings to Garmin a/o TrainerRoad"""

    # Withings API
    withings = WithingsAccount()

    if not ARGS.fromdate:
        startdate = withings.get_lastsync()
    else:
        startdate = int(time.mktime(ARGS.fromdate.timetuple()))

    enddate = int(time.mktime(ARGS.todate.timetuple())) + 86399
    logging.info(
        "Fetching measurements from %s to %s",
        time.strftime("%Y-%m-%d %H:%M", time.gmtime(startdate)),
        time.strftime("%Y-%m-%d %H:%M", time.gmtime(enddate)),
    )

    height = withings.get_height()
    groups = withings.get_measurements(startdate=startdate, enddate=enddate)

    # Only upload if there are measurement returned
    if groups is None or len(groups) == 0:
        logging.error("No measurements to upload for date or period specified")
        return -1

    # Save this sync so we don't re-download the same data again (if no range has been specified)
    if not ARGS.fromdate:
        withings.set_lastsync()

    last_weight, last_date_time, syncdata = prepare_syncdata(height, groups)

    fit_data = generate_fitdata(syncdata)
    json_data = generate_jsondata(syncdata)
    csv_data = generate_csvdata(syncdata)

    if last_weight is None:
        logging.error("Invalid or no weight data detected, exiting...")
        return -1

    if ARGS.no_upload:
        logging.info("dry run: skipping upload & local file generation...")
        return 0

    # Upload to Trainer Road
    if ARGS.trainerroad_username:
        logging.info("Trainerroad username set -- attempting to sync")
        logging.info(" Last weight %s", last_weight)
        logging.info(" Measured %s", last_date_time)
        if sync_trainerroad(last_weight):
            logging.info("TrainerRoad update done!")
    else:
        logging.info("No Trainerroad username or a new measurement " "- skipping sync")

    # Upload to Garmin Connect
    if ARGS.garmin_username:
        logging.debug("attempting to upload fit file...")
        if sync_garmin(fit_data):
            logging.info("Fit file uploaded to Garmin Connect")
            write_to_file_when_needed(fit_data, json_data, csv_data)
    else:
        logging.info("No Garmin username - skipping sync")
    return 0


ARGS = get_args()
if ARGS.output:
    CSV_FILENAME = ARGS.output + ".csv"
    FIT_FILENAME = ARGS.output + ".fit"
    JSON_FILENAME = ARGS.output + ".json"
else:
    CSV_FILENAME = "withings-sync-log.csv"
    FIT_FILENAME = "withings-sync-log.fit"
    JSON_FILENAME = "withings-sync-log.json"


def main():
    """Main"""
    logging.basicConfig(
        level=logging.DEBUG if ARGS.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
    logging.debug("Script invoked with the following arguments: %s", ARGS)

    if sys.version_info < (3, 0):
        print("Sorry, requires Python3, not Python2.")
        sys.exit(1)

    sync()
