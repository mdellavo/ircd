var gulp = require('gulp');
var serve = require('gulp-serve');

gulp.task('default', function() {
});

gulp.task('serve', serve({
    port: 8081,
    root: 'public'
}));