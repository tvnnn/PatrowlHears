from django.core.management.base import BaseCommand
from common.utils import chunks
from cves.models import Vendor, Product, CPE
from data.tasks import import_cpe_batch_task
import json
import time
import os
from tqdm import tqdm

CHUNK_SIZE = 8

class Command(BaseCommand):
    help = 'Import CPE from JSON file'

    def add_arguments(self, parser):
        parser.add_argument('-i', '--input-file', type=str, help='Input file')

    def handle(self, *args, **options):
        start_time = time.time()
        input_file = options['input_file']

        # Validate the input file
        if not input_file or not os.path.exists(input_file):
            print("File not found. Exiting.")
            return

        print(f"Importing CPEs from file: {input_file}")

        # Load data from the input JSON file
        with open(input_file, 'r') as f:
            data = json.load(f).get('cpes', {})

        # Cache existing CPEs, Vendors, and Products
        print("Caching existing data...")
        existing_cpes = set(CPE.objects.values_list('vector', flat=True))
        vendors = {v.name: v for v in Vendor.objects.all()}
        products = {p.name: p for p in Product.objects.all()}

        # Prepare tasks for Celery
        tasks = []

        for vendor_name, vendor_data in tqdm(data.items(), desc="Preparing tasks"):
            # Use get_or_create to avoid duplicate entries
            vendor, _ = Vendor.objects.get_or_create(name=vendor_name)
            vendors[vendor_name] = vendor

            for product_name, product_data in vendor_data.items():
                # Use get_or_create for products as well
                product, _ = Product.objects.get_or_create(name=product_name, vendor=vendor)
                products[product_name] = product

                for cpe_vector, details in product_data.items():
                    if cpe_vector not in existing_cpes:
                        # Prepare a task entry
                        tasks.append((cpe_vector, details, product.id, vendor.id))
                        existing_cpes.add(cpe_vector)  # Prevent duplicate tasks

        print(f"Dispatching {len(tasks)} tasks in chunks of {CHUNK_SIZE}...")
        pbar = tqdm(total=len(tasks), desc="Dispatching tasks")
        for chunk in chunks(tasks, CHUNK_SIZE):
            import_cpe_batch_task.apply_async(args=[chunk], queue='data')
            pbar.update(len(chunk))
        pbar.close()

        elapsed_time = time.time() - start_time
        print(f"Task dispatch completed in {elapsed_time:.2f} seconds.")