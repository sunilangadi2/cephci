import traceback

from tests.cephfs.cephfs_utilsV1 import FsUtils
from utility.log import Log

log = Log(__name__)


def run(ceph_cluster, **kw):
    """
    Test operation:
    1. Create a subvolume_group name that does not exist
    2. Try to remove the subvolume_group name that does not exist
    3. The command should fail because the subvolume_group name does not exist.
    4. Check if the command is failed
    """
    try:
        tc = "CEPH-83574168"
        log.info(f"Running CephFS tests for BZ-{tc}")
        test_data = kw.get("test_data")
        fs_util = FsUtils(ceph_cluster, test_data=test_data)
        erasure = (
            FsUtils.get_custom_config_value(test_data, "erasure")
            if test_data
            else False
        )
        clients = ceph_cluster.get_ceph_objects("client")
        client1 = clients[0]
        fs_name = "cephfs" if not erasure else "cephfs-ec"
        fs_details = fs_util.get_fs_info(client1, fs_name)

        if not fs_details:
            fs_util.create_fs(client1, fs_name)
        fs_util.auth_list([client1])
        target_delete_subvolume_group = "non_exist_subvolume_group_name"
        c_out, c_err = fs_util.remove_subvolumegroup(
            client1,
            f"{fs_name}",
            target_delete_subvolume_group,
            validate=False,
            check_ec=False,
        )
        if c_err:
            return 0
        return 1
    except Exception as e:
        log.info(e)
        log.info(traceback.format_exc())
        return 1
