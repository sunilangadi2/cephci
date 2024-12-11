"""
Module to verify successful live migration of RBD images from
one ceph cluster to another ceph cluster with native data format.

Pre-requisites:
- Two Ceph clusters deployed and accessible.
- A common client node configured to access both clusters.
- `ceph-common` package installed with live migration binaries available.

Test steps covered:
1. Configure the common client node to access both clusters.
2. Create replicated pools and EC pools and initialize them on both clusters.
3. Create and write data to an RBD image, including a snapshot.
4. Execute live migration using native RBD source specification.
"""

import json

from ceph.rbd.initial_config import initial_rbd_config
from ceph.rbd.utils import getdict, random_string
from ceph.rbd.workflows.cleanup import cleanup
from ceph.rbd.workflows.migration import verify_migration_state
from ceph.utils import get_node_by_id
from cli.rbd.rbd import Rbd
from utility.log import Log

log = Log(__name__)


def configure_common_client_node(client, cluster_dict):
    """
    Configure the common client node to access both clusters.
    Args:
        client: Common client node object
        cluster_dict: Dictionary with cluster names as keys and cluster objects as values
    """
    for cluster_name, cluster in cluster_dict.items():
        conf_path = f"/etc/ceph/{cluster_name}.conf"
        keyring_path = f"/etc/ceph/{cluster_name}.client.admin.keyring"
        for file in ["ceph.conf", "ceph.client.admin.keyring"]:
            client.exec_command(
                cmd=f"scp {cluster.get_nodes(role='mon')[0].hostname}:/etc/ceph/{file} {conf_path if 'conf' in file else keyring_path}"
            )
    for cluster_name in cluster_dict.keys():
        out, err = client.exec_command(
            cmd=f"ceph -s --cluster {cluster_name}", output=True
        )
        if "HEALTH_OK" not in out:
            raise Exception(f"Failed to access cluster {cluster_name} from client")


def prepare_migration_source_spec(cluster_name, pool_name, image_name, snap_name):
    """
    Create a native source spec file for migration.
    Args:
        cluster_name: Name of the source cluster
        pool_name: Name of the source pool
        image_name: Name of the source image
        snap_name: Name of the snapshot
    Returns:
        Path to the native spec file
    """
    native_spec = {
        "cluster_name": cluster_name,
        "type": "native",
        "pool_name": pool_name,
        "image_name": image_name,
        "snap_name": snap_name,
    }
    spec_path = f"/tmp/native_spec_{random_string()}.json"
    with open(spec_path, "w") as spec_file:
        json.dump(native_spec, spec_file)
    return spec_path


def test_external_rbd_image_migration(rbd_obj, client, cluster1, cluster2, **kw):
    """
    Test to perform live migration of images with native data format.
    Args:
        rbd_obj: rbd object
        client: Common client node object
        cluster1: Source cluster object
        cluster2: Destination cluster object
        kw: Key/value pairs of configuration information to be used in the test
    """
    pool_name = random_string()
    image_name = random_string()
    dest_pool_name = random_string()
    dest_image_name = random_string()
    snap_name = "snap1"

    # Step 1: Configure the common client node
    configure_common_client_node(client, {"cluster1": cluster1, "cluster2": cluster2})

    # Step 2: Create and initialize pools on both clusters
    create_and_initialize_pool(rbd_obj, "cluster1", pool_name)
    create_and_initialize_pool(rbd_obj, "cluster2", dest_pool_name)

    # Step 3: Create RBD image and write data
    checksum = create_image_and_write_data(rbd_obj, "cluster1", pool_name, image_name)

    # Step 4: Create snapshot
    rbd_obj.snapshot.create(pool_name, image_name, snap_name, cluster="cluster1")

    # Step 5: Prepare source spec for migration
    spec_path = prepare_migration_source_spec(
        "cluster1", pool_name, image_name, snap_name
    )

    # Step 6: Execute prepare migration
    rbd_obj.migration.prepare(
        source_spec_path=spec_path,
        dest_spec=f"{dest_pool_name}/{dest_image_name}",
        cluster="cluster2",
    )

    # Step 7: Execute migration and verify
    rbd_obj.migration.action(
        "execute", dest_spec=f"{dest_pool_name}/{dest_image_name}", cluster="cluster2"
    )
    rbd_obj.migration.verify_migration(
        "commit", dest_spec=f"{dest_pool_name}/{dest_image_name}", cluster="cluster2"
    )

    log.info("RBD image migration test completed successfully.")


def run(**kw):
    """
    Test to execute Live image migration with native data format
    from external ceph cluster.
    Args:
        kw: Key/value pairs of configuration information to be used in the test
            Example::
            config:
                do_not_create_image: True
                rep_pool_config:
                    num_pools: 2
                    size: 4G
                ec_pool_config:
                    num_pools: 2
                    size: 4G
                create_pool_parallely: true
    """
    log.info(
        "Executing CEPH-83597689: Live migration of images with native \
        data format from external ceph cluster"
    )
    try:
        rbd_obj = initial_rbd_config(**kw)
        pool_types = rbd_obj.get("pool_types")

        client = (
            kw.get("ceph_cluster_dict").get("ceph-rbd1").get_nodes(role="client")[0]
        )
        configure_common_client_node(
            client=client,
            cluster_dict=kw.get("ceph_cluster_dict"),
        )
        ret_val = test_external_rbd_image_migration(
            rbd_obj=rbd_obj, cluster1=cluster1, cluster2=cluster2, **kw
        )

    except Exception as e:
        log.error(
            f"RBD image migration with external ceph native format failed with the error {str(e)}"
        )
        ret_val = 1

    finally:
        cluster_name = kw.get("ceph_cluster", {}).name
        if "rbd_obj" not in locals():
            rbd_obj = Rbd(client)
        obj = {cluster_name: rbd_obj}
        cleanup(pool_types=pool_types, multi_cluster_obj=obj, **kw)

    return ret_val
