#!/usr/bin/env python
# Condensation build system.
# "It builds the cloud."
# A system for building Mesos images for a cluster (real or simulated).

import urllib2
import os
import sys
import math
import hashlib
import commands
from fnmatch import fnmatch
import tarfile
from argparse import ArgumentParser

condensation_version = '0.1'

scala_version = '2.10.4'
spark_version = '1.0.0'

script_loc = os.path.dirname(os.path.realpath(__file__))

def make_all(domain, zk_conn):
  make_externals()
  make_containers(domain, zk_conn)

def make_externals():
  banner("Getting external packages to include in builds...")

  scala_url = 'http://www.scala-lang.org/files/archive/scala-%s.tgz' % scala_version
  scala_sha256 = 'b46db638c5c6066eee21f00c447fc13d1dfedbfb60d07db544e79db67ba810c3'

  spark_url = 'http://d3kbcqa49mib13.cloudfront.net/spark-%s-bin-hadoop2.tgz' % spark_version
  spark_sha256 = 'cda5a74c3d0516562ca35023f903916cc91a1a63b5324c785eee57c86f97c290'

  compute_externals = os.path.join(script_loc, 'compute', '_externals')
  if not os.path.isdir(compute_externals):
    os.mkdir(compute_externals)

  download(scala_url, scala_sha256, compute_externals)
  download(spark_url, spark_sha256, compute_externals)

def make_containers(domain, zk_conn):
  banner("Building containers and/or VM images for various node roles...")

  for root, _, files in os.walk(script_loc):
    for name in files:
      if fnmatch(name, '*.packer.json'):
        os.chdir(root)

        image_builds = os.path.join(root, '_builds')
        if not os.path.isdir(image_builds):
          os.mkdir(image_builds)

        build = os.path.join(root, name)

        user_vars = get_user_vars(domain, zk_conn)
        print("(make_containers): packer using uservars: %s" % user_vars)

        status_code, output = commands.getstatusoutput("packer validate %s %s" % (user_vars, build))
        if status_code == 256:
          sys.stderr.write("%s: fatal error: packer validation failed!\n\nOutput:\n--------\n %s\n" % (build, output))
          sys.exit(20)
        elif status_code == 0:
          print("%s: image build spec validated successfully." % build)
        else:
          sys.stderr.write("%s: fatal error: Packer validation failed! Unknown err code: %s. Do you have Packer installed and in your PATH?\n\nOutput:\n-------\n %s\n\n"
            % (build, status_code, output))
          sys.exit(status_code)

        print("%s: building images (this can take awhile)...\r" % build)
        status_code, output = commands.getstatusoutput("packer build %s %s" % (user_vars, build))
        if status_code == 256:
          sys.stderr.write("%s: fatal error: Packer image build failed!\n\nOutput:\n--------\n %s\n" % (build, output))
          sys.exit(20)
        elif status_code == 0:
          print("%s: build completed successfully. Images (if applicable) dumped to %s" % (build, os.path.join(root, "_builds")))
        else:
          sys.stderr.write("%s: fatal error: Packer image build failed! Unknown err code: %s. \n\nOutput:\n-------\n %s\n\n"
            % (status_code, build, output))
          sys.exit(status_code)

def get_user_vars(domain, zk_conn):
  # The quorum must be a majority of ZooKeeper peers
  zk_quorum = int(math.ceil((len(zk_conn.split(',')) - 1) / 2.0))

  return "-var 'spark_version=%s' -var 'scala_version=%s' -var 'condensation_version=%s' -var 'domain=%s' -var 'zk_conn=%s' -var 'zk_quorum=%s'" % (
         spark_version, scala_version, condensation_version, domain, zk_conn, zk_quorum)

def download(url, sha, out_path):
  file_name = url.split('/')[-1]
  file_path = os.path.join(out_path, file_name)

  if os.path.exists(file_path):
    with open(file_path, 'rb') as existing:
      actual_hash = hashlib.sha256(existing.read()).hexdigest()
    if actual_hash == sha:
      print(file_path + ": already exists and is valid. Skipping download...")
      tar_dir = file_path.replace(".tgz", "").replace(".tar.gz", "")
      if not os.path.isdir(tar_dir):
        untar(file_path, out_path)
      return

  resource = urllib2.urlopen(url)

  out = open(file_path, 'wb')

  size = int(resource.info()["Content-Length"])

  print("")
  print("%s: downloading... (Size: %s bytes)" % (file_name, size))
  bytes_downloaded = 0

  while True:
    buffer = resource.read(4096)
    if not buffer:
      break

    bytes_downloaded += len(buffer)
    out.write(buffer)
    sys.stdout.write("%10d  [%3.2f%%] \r" % (bytes_downloaded, bytes_downloaded * 100. / size))
    sys.stdout.flush()

  print("%10d  [%3.2f%%] \r" % (bytes_downloaded, bytes_downloaded * 100. / size))
  print("")
  out.close()

  with open(file_path, 'rb') as existing:
    actual_hash = hashlib.sha256(existing.read()).hexdigest()
  if not actual_hash == sha:
     sys.stderr.write("%s: fatal error: Downloaded file does not have the expected hash digest!\n" % file_path)
     sys.exit(10)

  untar(file_path, out_path)

def untar(file_path, out_path):
  print ("%s: extracting archive..." % file_path)
  tar = tarfile.open(file_path)
  tar.extractall(out_path)
  tar.close()

def banner(str):
  print("")
  print("="*(len(str)+2))
  print(" %s " % str)
  print("="*(len(str)+2))
  print("")

def main():
  parser = ArgumentParser(description="If no build targets are specified, the assumption is to build everything.")
  parser.add_argument('-d', '--domain', dest='domain',
                    help='Domain NAME shared by all nodes in the cluster.',
                    default='example.com', metavar='NAME')
  parser.add_argument('-z', '--zookeeper-conn', dest='zk_conn',
                    help='Provide a ZooKeeper connection string (the part after the zk://, see Mesos docs for details). This MUST be specified if you are building an actual cluster.',
                    default='localhost:2181,/mesos', metavar='STRING')
  parser.add_argument('-u', '--user-vars', dest='user_vars', action='store_true',
                    help='Print the Packer user variables used that would be used for a build and exit.',
                    default=False)
  parser.add_argument('--target-get-externals', dest='opt_externals', action='store_true',
                    help='Get all external depedencies.',
                    default=False)
  parser.add_argument('--target-build-containers', dest='opt_containers', action='store_true',
                    help='Build the containers.',
                    default=False)
  args = parser.parse_args()

  if args.user_vars:
    print(get_user_vars(args.domain, args.zk_conn))
    return

  banner(" " * 10 + "Condensation: It's how clouds are made." + " " * 10)
  print(" " * 18 + "Version " + condensation_version)
  print("")

  if not args.opt_externals and not args.opt_containers:
    make_all(args.domain, args.zk_conn)
  elif args.opt_externals:
    make_externals()
  if args.opt_containers:
    make_containers(args.domain, args.zk_conn)

if __name__ == "__main__":
  main()
