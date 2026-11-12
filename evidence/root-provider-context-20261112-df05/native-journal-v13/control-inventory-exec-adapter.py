import os,sys
fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
os.dup2(fd,1)
os.close(fd)
os.execvpe(sys.argv[2],sys.argv[2:],os.environ)
