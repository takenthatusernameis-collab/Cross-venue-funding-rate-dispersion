import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from controller_progress import has_meaningful_committed_progress


def git(repo,*args):
    return subprocess.run(["git","-C",str(repo),*args],check=True,capture_output=True,text=True).stdout.strip()


class ControllerProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.repo=Path(self.temp.name)
        git(self.repo,"init","-b","main")
        git(self.repo,"config","user.name","initial")
        git(self.repo,"config","user.email","initial@example.invalid")
        (self.repo/"baseline.txt").write_text("baseline\n")
        git(self.repo,"add","baseline.txt"); git(self.repo,"commit","-m","initial")
        self.base=git(self.repo,"rev-parse","HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def commit_kilo(self,path,content):
        target=self.repo/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(content)
        git(self.repo,"add",path)
        git(self.repo,"-c","user.name=kilo-autonomous","-c","user.email=kilo-autonomous@users.noreply.github.com","commit","-m","agent checkpoint")
        return git(self.repo,"rev-parse","HEAD")

    def test_progress_requires_matching_remote_sha_for_credit(self):
        head=self.commit_kilo("src/new.py","value=1\n")
        self.assertTrue(has_meaningful_committed_progress(self.repo,self.base,head))
        self.assertFalse(has_meaningful_committed_progress(self.repo,self.base,head,"wrong"))
        self.assertTrue(has_meaningful_committed_progress(self.repo,self.base,head,head))

    def test_workflow_only_change_is_not_project_progress(self):
        head=self.commit_kilo(".github/workflows/main.yml","name: test\n")
        self.assertFalse(has_meaningful_committed_progress(self.repo,self.base,head,head))


if __name__=="__main__":
    unittest.main()
