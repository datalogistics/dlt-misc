import asyncio
import concurrent.futures
import getpass
import os
import re
import time
import types
import uuid

from functools import partial
from itertools import cycle
from concurrent.futures import ThreadPoolExecutor, as_completed
from uritools import urisplit
from socketIO_client import SocketIO

from lace import logging
from lace.logging import trace

from libdlt.util import util
from libdlt.depot import Depot
from libdlt.protocol import factory
from libdlt.protocol.exceptions import AllocationError
from libdlt.schedule import BaseDownloadSchedule, BaseUploadSchedule
from libdlt.settings import DEPOT_TYPES, THREADS, COPIES, BLOCKSIZE, TIMEOUT
from libdlt.result import UploadResult, DownloadResult, CopyResult
from unis.models import Exnode, Service
from unis.runtime import Runtime
from unis.utils.asynchronous import make_async

class Session(object):
    __WS_MTYPE = {
        'r' : 'peri_download_register',
        'c' : 'peri_download_clear',
        'p' : 'peri_download_pushdata'
    }
    
    __static_ips = {
        '149.165.232.115': 'mon01.crest.iu.edu',
        '10.10.1.1': 'mon1.apt.emulab.net'
    }
    
    @trace.debug("Session")
    def __init__(self, url, depots, bs=BLOCKSIZE, timeout=TIMEOUT, threads=THREADS, **kwargs):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        self._external_rt = isinstance(url, Runtime)
        self._runtime = url if isinstance(url, Runtime) else Runtime(url, proxy={'defer_update': True, 'subscribe': False})
        self._runtime.exnodes.createIndex("name")
        self._do_flush = True
        self._blocksize = bs if isinstance(bs, int) else int(util.human2bytes(bs))
        self._timeout = timeout
        self._plan = cycle
        self._depots = {}
        self._threads = threads
        self._viz = kwargs.get("viz_url", None)
        self._jobs = asyncio.Queue()
        self.log = logging.getLogger('libdlt')
        self._record = []
        
        if not depots:
            for depot in self._runtime.services.where(lambda x: x.serviceType in DEPOT_TYPES):
                self._depots[depot.accessPoint] = depot
        elif isinstance(depots, str):
            with Runtime(depots) as rt:
                for depot in rt.services.where(lambda x: x.serviceType in DEPOT_TYPES):
                    self._depots[depot.accessPoint] = depot
        elif isinstance(depots, dict):
            for name, depot in depots.items():
                if isinstance(depot, dict) and depot["enabled"]:
                    self._depots[name] = Service(depot)
        else:
            raise ValueError("depots argument must contain a list of depot description objects or a valid unis url")

        if not len(self._depots):
            raise ValueError("No depots found for session, unable to continue")

    def get_record(self):
        return self._record
    
    @trace.debug("Session")
    def _viz_register(self, name, size, conns):
        if self._viz:
            try:
                uid = uuid.uuid4().hex
                o = urisplit(self._viz)
                sock = SocketIO(o.host, o.port)
                msg = {"sessionId": uid,
                       "filename": name,
                       "size": size,
                       "connections": conns,
                       "timestamp": time.time()*1e3
                   }
                sock.emit(self.__WS_MTYPE['r'], msg)
                return uid, sock, name, size
            except Exception as e:
                self.log.warn(e)
        return None
            
    @trace.debug("Session")
    def _viz_progress(self, sock, depot, size, offset, cb):
        try:
            d = Depot(depot)
            if cb:
                cb(d, sock[2], sock[3], size, offset)
            if self._viz:
                host = str(d.host)
                if host in self.__static_ips:
                    host = self.__static_ips[host]
                msg = {"sessionId": sock[0],
                       "host":  host,
                       "length": size,
                       "offset": offset,
                       "timestamp": time.time()*1e3
                }
                sock[1].emit(self.__WS_MTYPE['p'], msg)
        except:
            pass

    @trace.debug("Session")
    def _generate_jobs(self, step, size, copies):
        for chunk in range(0, size, step):
            for _ in range(copies):
                self._jobs.put_nowait((chunk, step))
    
    @trace.debug("Session")
    async def _upload_chunks(self, path, schedule, duration, sock, rank, progress_cb):
        uploaded = 0
        allocs = []
        with open(path, 'rb') as fh:
            while not self._jobs.empty():
                offset, size = await self._jobs.get()
                fh.seek(offset)
                data = await asyncio.get_event_loop().run_in_executor(None, fh.read, size)
                rsize = len(data)
                
                ## Upload chunk ##
                try:
                    d = Depot(schedule.get({"offset": offset, "size": len(data), "data": data}))
                except Exception as exp:
                    self.log.warn("Failed to schedule chunk upload - {}".format(exp))
                    continue
                try:
                    fn = partial(factory.makeAllocation, **{**{'duration': duration},
                                                            **self._depots[d.endpoint].to_JSON()})
                    alloc = await asyncio.get_event_loop().run_in_executor(None, fn, data, offset, d)
                except AllocationError:
                    self._jobs.put_nowait((offset, size))
                    continue
                
                ## Create Allocation ##
                alloc = alloc.getMetadata()
                self._record.append(('U', alloc, offset, rsize))
                self._viz_progress(sock, alloc.location, alloc.size, alloc.offset, progress_cb)
                self.log.info("[{}] Uploaded: {}-{}".format(rank, offset, offset+rsize))
                allocs.append(alloc)
                uploaded += len(data)

        return (uploaded, allocs)
        
    @trace.info("Session")
    def upload(self, path, filename=None, folder=None, copies=COPIES, duration=None, schedule=None, progress_cb=None):
        async def _awrapper(schedule, sock):
            workers = [self._upload_chunks(path, schedule, duration, sock, r, progress_cb) for r in range(self._threads)]
            result = await asyncio.gather(*workers)
            return result
        
        schedule = schedule or BaseUploadSchedule()
        ## Create Folder ##
        if isinstance(folder, str):
            do_flush = self._do_flush
            self._do_flush = False
            folder = self.mkdir(folder)
            self._do_flush = do_flush
            
        ## Setup ##
        stat = os.stat(path)
        ex = Exnode({ "parent": folder, "created": int(time.time() * 1000000), "mode": "file",
                      "size": stat.st_size, "permission": format(stat.st_mode & 0o0777, 'o'),
                      "owner": getpass.getuser(), "name": filename or os.path.basename(path) })
        ex.group = ex.owner
        ex.updated = ex.created
        sock = self._viz_register(ex.name, ex.size, len(self._depots))
        if len(self._depots) < copies:
            print("Cannot create {} replica, not enough stores [{}]".format(copies, len(self._depots)))
            return
        
        schedule.setSource(self._depots)

        time_s = time.time()
        uploaded = 0
        all_allocs = []
        ## Generate tasks ##
        self._generate_jobs(self._blocksize, ex.size, copies)
        for upsize, allocs in make_async(_awrapper, schedule, sock):
            uploaded += upsize
            all_allocs.extend(allocs)
        
        time_e = time.time()
        self._runtime.insert(ex, commit=True)
        for alloc in all_allocs:
            alloc.parent = ex
            alloc.getObject().__dict__['selfRef'] = ''
            del alloc.getObject().__dict__['function']
            ex.extents.append(alloc)
            self._runtime.insert(alloc, commit=True)

        if self._do_flush:
            self._runtime.flush()

        return UploadResult(time_e - time_s, uploaded, ex)
    
    
    @trace.debug("Session")
    async def _download_chunks(self, filepath, schedule, sock, rank, progress_cb):
        def _write(fh, offset, data):
            async def _noop():
                return 0
            fh.seek(offset)
            if data:
                return asyncio.get_event_loop().run_in_executor(None, fh.write, data)
            return _noop()
        fh = open(filepath, 'wb')
        downloaded = 0
        while not self._jobs.empty():
            offset, end = self._jobs.get_nowait()
            try:
                alloc = schedule.get({"offset": offset})
            except IndexError as exp:
                self.log.warn(exp)
                continue
            if alloc.offset + alloc.size < end:
                await self._jobs.put((offset + alloc.size, end))
            
            ## Download chunk ##
            d = Depot(alloc.location)
            service = factory.buildAllocation(alloc)
            loop = asyncio.get_event_loop()
            try:
                fn = partial(service.read, **self._depots[d.endpoint].to_JSON())
                data = await loop.run_in_executor(None, fn)
            except AllocationError as exp:
                self.log.warn("Unable to download block - {}".format(exp))
                await self._jobs.put((offset, offset + alloc.size))
                continue
            if data:
                self._record.append(('D', alloc, offset, len(data)))
                self.log.info("[{}] Downloaded: {}-{}".format(rank, offset, offset+len(data)))
                self._viz_progress(sock, alloc.location, alloc.size, alloc.offset, progress_cb)
                length = await _write(fh, alloc.offset, data)
                downloaded += length
            else:
                await self._jobs.put((offset, offset + alloc.size))
        
        fh.close()
        return downloaded
        
    @trace.info("Session")
    def download(self, href, folder=None, length=0, offset=0, schedule=None, progress_cb=None, filename=None):
        async def _awrapper(folder, schedule, sock):
            workers = [self._download_chunks(folder, schedule, sock, r, progress_cb) for r in range(self._threads)]
            return await asyncio.gather(*workers)

        schedule = schedule or BaseDownloadSchedule()
        ex = next(self._runtime.exnodes.where({'selfRef': href}))
        allocs = ex.extents
        schedule.setSource(allocs)
        locs = {}
        
        # bin extents and locations
        for alloc in allocs:
            if alloc.location not in locs:
                locs[alloc.location] = []
            locs[alloc.location].append(alloc)
        
        if not folder:
            folder = filename or ex.name
            
        # register download with Periscope
        sock = self._viz_register(ex.name, ex.size, len(locs))
        
        time_s = time.time()
        self._jobs.put_nowait((0, ex.size))
        if self._threads > 1:
            downloaded = sum(make_async(_awrapper, folder, schedule, sock))
        else:
            offset = 0
            with open(folder, 'wb') as fh:
                while offset < ex.size:
                    try:
                        alloc = schedule.get({"offset": offset})
                    except IndexError as exp:
                        self.log.warn(exp)
                        break
                    d = Depot(alloc.location)
                    service = factory.buildAllocation(alloc)
                    try:
                        data = service.read(**self._depots[d.endpoint].to_JSON())
                    except AllocationError as exp:
                        self.log.warn("Unable to download block - {}".format(exp))
                        continue
                    if data:
                        self.log.info("Downloaded: {}-{}".format(offset, offset+len(data)))
                        self._viz_progress(sock, alloc.location, alloc.size, alloc.offset, progress_cb)
                        fh.seek(alloc.offset)
                        length = fh.write(data)
                        offset += length
            downloaded = offset
        
        return DownloadResult(time.time() - time_s, downloaded, ex)
        
    @trace.info("Session")
    def copy(self, href, duration=None, download_schedule=BaseDownloadSchedule(), upload_schedule=BaseUploadSchedule(), progress_cb=None):
        def offsets(size):
            i = 0
            while i < size:
                ext = download_schedule.get({"offset": i})
                yield ext
                i += ext.size
        def _copy_chunk(name, size, sock_down, sock_up):
            def _f(ext):
                try:
                    alloc = factory.buildAllocation(ext)
                    src_desc = Depot(ext.location)
                    dest_desc = Depot(upload_schedule.get({"offset": ext.offset, "size": ext.size}))
                    src_depot = self._depots[src_desc.endpoint]
                    dest_depot = self._depots[dest_desc.endpoint]
                    dst_alloc = alloc.copy(dest_desc, src_depot.to_JSON(), dest_depot.to_JSON(), **kwargs)
                    dst_ext = dst_alloc.getMetadata()
                    self._viz_progress(sock_down, name, size, ext.location, ext.size, ext.offset, progress_cb)
                    self._viz_progress(sock_up, name, size, dst_ext.location, dst_ext.size, dst_ext.offset, progress_cb)
                    return (ext, dst_ext)
                except Exception as exp:
                    self.log.warn ("READ Error: {}".format(exp))
                return ext, False
            return _f
        
        ex = next(self._runtime.exnodes.where({'selfRef': href}))
        allocs = ex.extents
        futures = []
        download_schedule.setSource(allocs)
        upload_schedule.setSource(self._depots)
        
        sock_up = self._viz_register("{}_upload".format(ex.name), ex.size, len(self._depots))
        sock_down = self._viz_register("{}_download".format(ex.name), ex.size, len(self._depots))
        copied = 0
        time_s = time.time()
        with ThreadPoolExecutor(max_workers=self._threads) as executor:
            for src_alloc, dst_alloc  in executor.map(_copy_chunk(sock_down, sock_up), offsets(ex.size)):
                alloc = dst_alloc
                self._runtime.insert(alloc, commit=True)
                alloc.parent = ex
                ex.extents.append(alloc)
                copied += alloc.size
        
        time_e = time.time()
        
        if self._do_flush:
            self._runtime.flush()
        return (time_e - time_s, ex)
        
    @trace.info("Session")
    def mkdir(self, path):
        def _traverse(ls, obj):
            if not ls:
                return ([], obj)
            for child in obj.children:
                if child.name == ls[0]:
                    return _traverse(ls[1:], child)
            return (ls, obj)
        
        path = list(filter(None, path.split('/')))
        if not path:
            return
        
        folder_ls = list(self._runtime.exnodes.where({"name": path[0], "mode": "directory", "parent": None}))
        if folder_ls:
            path, root = _traverse(path[1:], folder_ls[0])
        else:
            root = None
        
        for folder in path:
            owner = getpass.getuser()
            now = int(time.time() * 1000000)
            new_folder = Exnode({"name": folder, 
                                 "parent": root, 
                                 "owner": owner, 
                                 "group": owner, 
                                 "created": now, 
                                 "updated": now, 
                                 "children": [], 
                                 "permission": format(0o0755, 'o'), 
                                 "mode": "directory"})
            self._runtime.insert(new_folder, commit=True)
            if root:
                if not hasattr(root, "children"):
                    root.children = [new_folder]
                    root.commit("children")
                else:
                    root.children.append(new_folder)
                    
            root = new_folder
        
        if self._do_flush:
            self._runtime.flush()
        
        return root

    @trace.debug("Session")
    def annotate(self, exnode):
        class _modifier:
            def __getattr__(self, n):
                exnode.__getattribute__(n)
            def __setattr__(self, n, v):
                exnode.__setattr__(n, v)
                exnode.commit(n)
            def __enter__(mod):
                pass
            def __exit__(mod, ex_ty, ex_val, tb):
                self._runtime.flush()
        return _modifier()
    
    
    def __enter__(self):
        return self

    def __exit__(self, ex_ty, ex_val, tb):
        if not self._external_rt:
            self._runtime.shutdown()
